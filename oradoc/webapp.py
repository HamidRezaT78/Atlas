"""Local data-entry app: add an Oracle or SQL Server database, store its password, generate and publish documentation.

    .venv\\Scripts\\pythonw.exe -m oradoc.webapp      (Atlas.cmd / the Atlas shortcut runs this)

Serves ui/oradoc_app.html on 127.0.0.1 only and opens it in the default browser. Every API call must
carry the per-launch token (X-Oradoc-Token) and a 127.0.0.1/localhost Host header, so other sites
cannot drive it. The password typed in the page goes straight to Windows Credential Manager (or is
used once for a connection test); it is never written to a file, a log or a response.
The app stops itself after IDLE_SECONDS without a page open and no job running.
"""
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import keyring

from . import mssql_queries, queries
from .collector import canonical_json, collect
from .config import ENGINES, MSSQL_NAME_RE, NAME_RE, PACKAGE_DIR, PROFILE_RE, Profile, check_object_name, load_config
from .db import connect, fetch, sanitize_error
from .engine import DEFAULT_DOCS_ROOT, OutputConflict, generate, generate_business, write_outputs
from .i18n import AUDIENCES, DETAILS, LANGS

PROJECT = PACKAGE_DIR.parent
CONFIG_PATH = PROJECT / "config" / "profiles.toml"
PAGE = PROJECT / "ui" / "oradoc_app.html"
PUBLISH = PROJECT / "tools" / "publish" / "publish.py"
LOG_PATH = PROJECT / "logs" / "oradoc_app.log"
INSTANCE_PATH = PROJECT / "logs" / "instance.json"  # port + token of the running instance (this user only)
# Fingerprint of the server code: a launch never reuses an instance that runs older code.
CODE_VERSION = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(PACKAGE_DIR.glob("*.py")))).hexdigest()[:12]
PREFERRED_PORT = 8765
IDLE_SECONDS = 15 * 60
MAX_BODY = 64 * 1024

HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}")
MSSQL_HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}(\\[A-Za-z0-9_$#\-]{1,16})?")  # host or host\INSTANCE
DEFAULT_PORT = {"oracle": 1521, "sqlserver": 1433}
DEFAULT_TIMEOUT_MS = {"oracle": 10000, "sqlserver": 30000}
SERVICE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-$#]{0,127}")
DELIVERABLE_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")
DSN_RE = re.compile(r"^(?P<host>[^:/]+):(?P<port>\d+)/(?P<service>.+)$")

# Known Oracle / SQL Server / driver errors -> a hint the person can act on (first match wins).
ERROR_HINTS = [
    ("18456", "نام کاربری یا رمز عبور اشتباه است، یا ورود با SQL Server Authentication روی سرور فعال نیست."),
    ("18486", "حساب کاربری قفل شده است."),
    ("18487", "رمز عبور منقضی شده است."),
    ("18488", "رمز عبور باید تغییر کند."),
    ("18470", "حساب کاربری غیرفعال است."),
    ("4060", "این دیتابیس باز نشد یا این کاربر به آن دسترسی ندارد."),
    ("20009", "اتصال به SQL Server برقرار نشد؛ آدرس، پورت (معمولاً 1433)، فعال بودن TCP/IP و فایروال را بررسی کنید."),
    ("20002", "اتصال به SQL Server برقرار نشد؛ آدرس، پورت و تنظیمات رمزگذاری سرور را بررسی کنید."),
    ("ORA-01017", "نام کاربری یا رمز عبور اشتباه است."),
    ("ORA-28000", "حساب کاربری قفل شده است."),
    ("ORA-28001", "رمز عبور منقضی شده است."),
    ("ORA-12514", "نام سرویس (Service name) روی این سرور شناخته نشد."),
    ("ORA-12541", "روی این آدرس و پورت listener اوراکل پیدا نشد."),
    ("DPY-6005", "اتصال به سرور برقرار نشد؛ آدرس، پورت و دسترسی شبکه را بررسی کنید."),
    ("DPY-4011", "اتصال توسط سرور قطع شد."),
    ("DPY-3010", "این نسخه اوراکل در حالت thin پشتیبانی نمی‌شود."),
    ("DPI-1047", "کتابخانه Oracle Client پیدا نشد."),
]


class UserError(Exception):
    """A message for the page, in Persian, safe to show."""


def friendly(exc, profile=None):
    text = sanitize_error(exc, profile) if profile else f"{type(exc).__name__}: {exc}"
    for code, hint in ERROR_HINTS:
        if code in text:
            return f"{hint} ({code})"
    return text


# ---------------------------------------------------------------------------
# Profiles (config/profiles.toml) and passwords (Windows Credential Manager)
# ---------------------------------------------------------------------------

def split_dsn(dsn):
    m = DSN_RE.match(dsn)
    return (m["host"], int(m["port"]), m["service"]) if m else (dsn, None, "")


def has_password(profile):
    try:
        return bool(keyring.get_password(profile.keyring_service, profile.username))
    except Exception:
        return False


def list_profiles():
    if not CONFIG_PATH.is_file():
        return {"profiles": [], "default": None}
    cfg = load_config(CONFIG_PATH)
    out = []
    for name, p in sorted(cfg["profiles"].items()):
        host, port, service = split_dsn(p.dsn)
        out.append({
            "name": name, "engine": p.engine, "host": host, "port": port, "service": service, "username": p.username,
            "schemas": list(p.allowed_schemas), "default_schema": p.default_schema,
            "has_password": has_password(p),
        })
    return {"profiles": out, "default": cfg["default_profile"]}


def existing_profile(name):
    if not name or not CONFIG_PATH.is_file():
        return None
    return load_config(CONFIG_PATH)["profiles"].get(name)


def connection_fields(body, database_optional=False):
    """Validate engine/host/port/service (Oracle) or database (SQL Server)/username from the page.

    Returns (dsn, username, engine). With database_optional, an empty SQL Server database means master
    (the connection test then lists the databases to choose from)."""
    engine = body.get("engine") or "oracle"
    if engine not in ENGINES:
        raise UserError("نوع دیتابیس نامعتبر است.")
    mssql = engine == "sqlserver"
    host = str(body.get("host", "")).strip()
    service = str(body.get("service", "")).strip()
    username = str(body.get("username", "")).strip()
    try:
        port = body.get("port")
        port = DEFAULT_PORT[engine] if port in (None, "") else int(port)
    except (TypeError, ValueError):
        port = 0
    if not (MSSQL_HOST_RE if mssql else HOST_RE).fullmatch(host):
        raise UserError("آدرس سرور معتبر نیست (نام یا IP، بدون فاصله"
                        + ("؛ برای instance نام‌دار: SERVER\\INSTANCE)." if mssql else ")."))
    if not 1 <= port <= 65535:
        raise UserError("پورت باید عددی بین ۱ تا ۶۵۵۳۵ باشد.")
    if mssql and not service and database_optional:
        service = "master"
    if mssql and ("/" in service or not MSSQL_NAME_RE.fullmatch(service)):
        raise UserError("نام دیتابیس معتبر نیست.")
    if not mssql and not SERVICE_RE.fullmatch(service):
        raise UserError("نام سرویس معتبر نیست.")
    if not (MSSQL_NAME_RE if mssql else NAME_RE).fullmatch(username):
        raise UserError("نام کاربری معتبر نیست.")
    return f"{host}:{port}/{service}", username, engine


def toml_str(value):
    return json.dumps(value, ensure_ascii=False)  # a TOML basic string for these validated values


def profile_block(name, dsn, username, keyring_service, schemas, default_schema, timeout_ms, engine="oracle"):
    return "\n".join([
        f"[profiles.{name}]",
        *([f"engine = {toml_str(engine)}"] if engine != "oracle" else []),
        f"dsn = {toml_str(dsn)}",
        f"username = {toml_str(username)}",
        f"keyring_service = {toml_str(keyring_service)}",
        f"allowed_schemas = [{', '.join(toml_str(s) for s in schemas)}]",
        f"default_schema = {toml_str(default_schema)}",
        f"call_timeout_ms = {int(timeout_ms)}",
    ]) + "\n"


def upsert_profile_text(text, name, block):
    """Replace the [profiles.<name>] table in text, or append it; comments elsewhere are kept."""
    pattern = re.compile(rf"^\[profiles\.{re.escape(name)}\][ \t]*\n.*?(?=^\[|\Z)", re.M | re.S)
    if pattern.search(text):
        return pattern.sub(lambda _m: block + "\n", text, count=1).rstrip("\n") + "\n"
    if not text.strip():
        text = f"default_profile = {toml_str(name)}\n"
    return text.rstrip("\n") + "\n\n" + block


def save_profile(body):
    name = str(body.get("name", "")).strip()
    if not PROFILE_RE.fullmatch(name):
        raise UserError("نام پروفایل فقط حروف لاتین، عدد، _ و - (حداکثر ۶۴ نویسه).")
    dsn, username, engine = connection_fields(body)
    schemas = []
    for s in body.get("schemas") or []:
        try:
            s = check_object_name(str(s), engine)
        except ValueError:
            raise UserError(f"نام schema معتبر نیست: {s}") from None
        if s.casefold() not in {x.casefold() for x in schemas}:
            schemas.append(s)
    if not schemas:
        raise UserError("حداقل یک schema را انتخاب کنید.")
    wanted = str(body.get("default_schema") or "").strip()
    default_schema = next((s for s in schemas if s.casefold() == wanted.casefold()), schemas[0])
    password = body.get("password") or ""
    if not isinstance(password, str):
        raise UserError("رمز عبور نامعتبر است.")

    old = existing_profile(name)
    if old and not body.get("replace"):
        raise UserError(f"پروفایل «{name}» از قبل وجود دارد.")
    keyring_service = old.keyring_service if old else f"Oradoc_{name}"
    timeout_ms = old.call_timeout_ms if old and old.engine == engine else DEFAULT_TIMEOUT_MS[engine]
    if not password and not (old and old.username == username and has_password(old)):
        raise UserError("رمز عبور را وارد کنید؛ برای این پروفایل رمزی ذخیره نشده است.")

    block = profile_block(name, dsn, username, keyring_service, schemas, default_schema, timeout_ms, engine)
    current = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.is_file() else ""
    _write_config(current, upsert_profile_text(current, name, block))
    if password:
        keyring.set_password(keyring_service, username, password)
    return {"ok": True, "name": name, "password_saved": bool(password)}


def _write_config(current, new_text):
    """Validate new_text with the real loader, back up the current file to config/_backup/, then replace it."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".toml.tmp")
    tmp.write_text(new_text, encoding="utf-8", newline="\n")
    try:
        load_config(tmp)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise UserError(f"فایل پروفایل‌ها معتبر نشد: {exc}") from None
    if current:
        backup = CONFIG_PATH.parent / "_backup"
        backup.mkdir(exist_ok=True)
        (backup / f"profiles_{datetime.now():%Y%m%d-%H%M%S-%f}.toml").write_text(current, encoding="utf-8", newline="\n")
    os.replace(tmp, CONFIG_PATH)


def remove_profile_text(text, name, remaining):
    """Drop the [profiles.<name>] table; a default_profile naming it moves to remaining[0] (or is dropped)."""
    pattern = re.compile(rf"^\[profiles\.{re.escape(name)}\][ \t]*\n.*?(?=^\[|\Z)", re.M | re.S)
    text, n = pattern.subn("", text, count=1)
    if not n:
        raise UserError(f"پروفایل «{name}» در فایل پیدا نشد.")
    default = re.compile(r'^default_profile\s*=\s*"([^"]*)"[ \t]*$', re.M)
    m = default.search(text)
    if m and m.group(1) == name:
        text = text[:m.start()] + (f"default_profile = {toml_str(remaining[0])}" if remaining else "") + text[m.end():]
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n") + "\n"


def delete_profile(body):
    """Remove a profile from profiles.toml and, unless another profile shares it, its stored password.

    Generated documents under docs/ are kept."""
    name = str(body.get("name", "")).strip()
    old = existing_profile(name)
    if not old:
        raise UserError("این پروفایل پیدا نشد.")
    with JOB_LOCK:
        if JOB.get("state") == "running" and JOB.get("profile") == name:
            raise UserError("برای این پروفایل یک عملیات در حال اجراست؛ بعد از پایان آن حذف کنید.")
    remaining = [p for n, p in load_config(CONFIG_PATH)["profiles"].items() if n != name]
    current = CONFIG_PATH.read_text(encoding="utf-8")
    _write_config(current, remove_profile_text(current, name, [p.name for p in remaining]))
    shared = any(p.keyring_service == old.keyring_service and p.username == old.username for p in remaining)
    password_deleted = False
    if body.get("delete_password", True) and not shared:
        try:
            keyring.delete_password(old.keyring_service, old.username)
            password_deleted = True
        except Exception:  # nothing stored (or already removed)
            pass
    return {"ok": True, "name": name, "password_deleted": password_deleted, "password_shared": shared}


def test_connection(body):
    """Connect read-only and list the schemas this user can see; nothing is saved.

    SQL Server also returns the databases the login can open and a warning when it can write."""
    dsn, username, engine = connection_fields(body, database_optional=True)
    password = body.get("password") or ""
    old = existing_profile(str(body.get("name", "")).strip())
    profile = Profile(name="test", dsn=dsn, username=username,
                      keyring_service=old.keyring_service if old else "-",
                      allowed_schemas=(), default_schema="",
                      call_timeout_ms=old.call_timeout_ms if old and old.engine == engine else DEFAULT_TIMEOUT_MS[engine],
                      engine=engine)
    if not password and not (old and old.username == username and has_password(old)):
        raise UserError("برای تست اتصال رمز عبور را وارد کنید.")
    q = mssql_queries if engine == "sqlserver" else queries
    databases, warnings, perms = [], [], {}
    try:
        with connect(profile, password=password or None) as conn:
            version = fetch(conn, q.DB_VERSION)
            owners = fetch(conn, q.LIST_OWNERS)
            if engine == "sqlserver":
                databases = [r["name"] for r in fetch(conn, q.LIST_DATABASES)]
                perms = fetch(conn, q.PERMISSIONS)[0]
    except Exception as exc:
        raise UserError(friendly(exc, profile)) from None
    if engine == "sqlserver":
        powerful = [k for k in ("sysadmin", "db_owner", "db_ddladmin", "db_datawriter") if perms.get(k) == 1]
        if powerful:
            warnings.append(f"این کاربر دسترسی تغییر دارد ({', '.join(powerful)}). اطلس فقط می‌خواند، ولی برای امنیت بیشتر "
                            "از کاربری استفاده کنید که روی این دیتابیس فقط مجوز VIEW DEFINITION دارد.")
        if not owners:
            warnings.append("هیچ جدولی دیده نمی‌شود؛ کاربر روی این دیتابیس به مجوز VIEW DEFINITION نیاز دارد.")
        label = str((version[0] if version else {}).get("version") or "")
    else:
        main = next((v for v in version if "Oracle" in str(v.get("product", ""))), version[0] if version else {})
        label = f"{main.get('product', '')} {main.get('version', '')}".strip()
    return {
        "ok": True,
        "engine": engine,
        "version": label,
        "database": split_dsn(dsn)[2] if engine == "sqlserver" else None,
        "databases": databases,
        "warnings": warnings,
        "owners": [{"owner": o["owner"], "tables": int(o["n"])} for o in owners],
    }


# ---------------------------------------------------------------------------
# Documentation job (one at a time, in a background thread)
# ---------------------------------------------------------------------------

JOB_LOCK = threading.Lock()
JOB = {}


def job_snapshot():
    with JOB_LOCK:
        return json.loads(json.dumps(JOB, ensure_ascii=False)) if JOB else None


def job_running():
    with JOB_LOCK:
        return JOB.get("state") == "running"


def _log(line):
    with JOB_LOCK:
        JOB["log"].append(line)


def _step(index, status, note=None):
    with JOB_LOCK:
        JOB["steps"][index]["status"] = status
        if note:
            JOB["steps"][index]["note"] = note


def ai_key_status():
    from . import business_ai
    return {"has_key": bool(business_ai.get_key()), "model": business_ai.DEFAULT_MODEL}


def ai_key_save(body):
    """Check the Claude API key with a free Models API call, then store it in Credential Manager."""
    from . import business_ai
    key = str(body.get("key") or "").strip()
    if not key.startswith("sk-ant-") or len(key) > 300 or any(ch.isspace() for ch in key):
        raise UserError("کلید API معتبر نیست (باید با sk-ant- شروع شود).")
    try:
        business_ai.check_key(key)
    except business_ai.AIError as exc:
        raise UserError(str(exc)) from None
    business_ai.set_key(key)
    return ai_key_status()


def ai_key_delete(body):
    from . import business_ai
    business_ai.delete_key()
    return ai_key_status()


def start_job(body):
    name = str(body.get("profile", "")).strip()
    profile = existing_profile(name)
    if not profile:
        raise UserError("پروفایل انتخاب‌شده پیدا نشد؛ اول آن را ذخیره کنید.")
    try:
        schema = profile.check_schema(body.get("schema"))
    except ValueError:
        raise UserError("این schema در فهرست مجاز پروفایل نیست.") from None
    if not has_password(profile):
        raise UserError("برای این پروفایل رمزی در Windows Credential Manager ذخیره نشده است.")
    langs = [l for l in LANGS if l in (body.get("langs") or [])]
    audiences = [a for a in AUDIENCES if a in (body.get("audiences") or [])]
    detail = body.get("detail", "full")
    if detail not in DETAILS:
        raise UserError("سطح جزئیات نامعتبر است.")
    publish = bool(body.get("publish"))
    service = str(body.get("service") or re.sub(r"[^A-Za-z0-9_\-]", "_", split_dsn(profile.dsn)[2])).strip().upper()
    if publish:
        if not DELIVERABLE_RE.fullmatch(service):
            raise UserError("نام فایل تحویلی فقط حروف لاتین، عدد، _ و - باشد.")
        langs = sorted(set(langs) | {"fa"}, key=LANGS.index)
        audiences = sorted(set(audiences) | {"technical", "client"}, key=AUDIENCES.index)
    if not langs or not audiences:
        raise UserError("حداقل یک زبان و یک نسخه را انتخاب کنید.")
    business_ai = bool(body.get("business_ai"))
    business = bool(body.get("business")) or business_ai
    if business_ai and not ai_key_status()["has_key"]:
        raise UserError("برای غنی‌سازی با Claude ابتدا کلید API را ذخیره کنید.")

    combos = [(l, a) for l in langs for a in audiences]
    lang_fa = {"fa": "فارسی", "en": "انگلیسی"}
    steps = [{"label": "خواندن ساختار از دیتابیس", "status": "pending"}]
    steps += [{"label": f"مستند {lang_fa[l]} — {'فنی' if a == 'technical' else 'کارفرما'}",
               "status": "pending"} for l, a in combos]
    if business:
        steps += [{"label": f"تحلیل بیزنسی — {lang_fa[l]}" + (" (با Claude)" if business_ai else ""),
                   "status": "pending"} for l in langs]
    if publish:
        steps.append({"label": "ساخت Word و draw.io" + (" و Word بیزنسی" if business else ""), "status": "pending"})
    with JOB_LOCK:
        if JOB.get("state") == "running":
            raise UserError("یک عملیات دیگر در حال اجراست.")
        JOB.clear()
        JOB.update({"id": secrets.token_hex(4), "state": "running", "profile": name, "schema": schema,
                    "started": datetime.now().isoformat(timespec="seconds"),
                    "steps": steps, "log": [], "outputs": [], "folders": [], "warnings": []})
    args = (profile, schema, combos, detail, publish, service, langs if business else [], business_ai)
    threading.Thread(target=_run_job, args=args, daemon=True).start()
    return job_snapshot()


def _run_job(profile, schema, combos, detail, publish, service, business_langs=(), business_ai=False):
    i = 0
    try:
        run = DEFAULT_DOCS_ROOT / profile.name / schema / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
        _step(0, "running")
        _log(f"اتصال فقط‌خواندنی به {profile.name} و خواندن schema {schema} …")
        try:
            snap = collect(profile, schema)
        except Exception as exc:
            raise UserError(friendly(exc, profile)) from None
        snap_path = run / f"{schema}_snapshot.json"
        write_outputs(run, {snap_path: canonical_json(snap) + "\n"})
        failed = [k for k, v in snap["sections"].items() if v["status"] == "failed"]
        n_cols = sum(len(t["columns"]) for t in snap["tables"].values())
        _log(f"{len(snap['tables'])} جدول و {n_cols} ستون خوانده شد.")
        with JOB_LOCK:
            JOB["folders"].append(str(run))
            JOB["outputs"].append(str(snap_path))
        _step(0, "warn" if failed else "done", f"بخش ناموفق: {', '.join(failed)}" if failed else None)

        for i, (lang, audience) in enumerate(combos, start=1):
            _step(i, "running")
            result = generate(snapshot_path=snap_path, schema=schema, lang=lang, detail=detail,
                              out_dir=run, audience=audience)
            with JOB_LOCK:
                JOB["outputs"].append(result["files"]["markdown"])
            if result["passed"]:
                _step(i, "done")
            else:
                missing = sum(len(it["missing"]) for it in result["coverage"]["items"].values())
                _step(i, "warn", f"پوشش ناقص ({missing} مورد)")
                with JOB_LOCK:
                    JOB["warnings"].append(f"پوشش مستند {lang}/{audience} کامل نیست.")
        with JOB_LOCK:
            JOB["outputs"].append(str(run / f"{schema}_erd.mmd"))

        for i, lang in enumerate(business_langs, start=len(combos) + 1):
            _step(i, "running")
            if business_ai:
                _log(f"تحلیل بیزنسی ({lang}) با Claude: فقط ساختار ارسال می‌شود، نه داده‌ها …")
            result = generate_business(snapshot_path=snap_path, out_dir=run, lang=lang, ai=business_ai, log=_log)
            with JOB_LOCK:
                JOB["outputs"].append(result["markdown"])
                JOB["warnings"] += result["warnings"]
            note = f"حدود ${result['ai']['usage']['cost_usd']}" if result["ai"] and result["ai"]["usage"] else None
            _step(i, "warn" if result["warnings"] or not result["passed"] else "done", note)

        if publish:
            i = len(combos) + len(business_langs) + 1
            _step(i, "running")
            _log("ساخت فایل‌های Word و draw.io (چند دقیقه طول می‌کشد) …")
            target = DEFAULT_DOCS_ROOT / profile.name / service
            code = _run_publish(run, service, profile.name)
            if code != 0:
                raise UserError("انتشار Word/draw.io کامل نشد؛ جزئیات در گزارش بالا آمده است.")
            stamp = datetime.now().strftime("%Y%m%d")
            with JOB_LOCK:
                JOB["folders"].insert(0, str(target))
                JOB["outputs"] += [str(target / f"{service}_{stamp}_{s}") for s in ("dev.docx", "client.docx", "erd.drawio")
                                   + (("business.docx",) if "fa" in business_langs else ())]
            _step(i, "done")
        with JOB_LOCK:
            JOB["state"] = "done"
            JOB["finished"] = datetime.now().isoformat(timespec="seconds")
    except Exception as exc:
        msg = str(exc) if isinstance(exc, (UserError, OutputConflict)) else friendly(exc, profile)
        if not isinstance(exc, (UserError, OutputConflict)):
            _write_log(traceback.format_exc())
        _step(i, "failed")
        _log("خطا: " + msg)
        with JOB_LOCK:
            JOB["state"] = "failed"
            JOB["error"] = msg
            JOB["finished"] = datetime.now().isoformat(timespec="seconds")


def _python_exe():
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if console.is_file() else exe)


def _run_publish(run, service, profile_name):
    cmd = [_python_exe(), str(PUBLISH), "--run", str(run), "--service", service, "--profile", profile_name]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen(cmd, cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", creationflags=flags, env=env)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            _log(line)
    return p.wait()


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

def _write_log(text):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text.rstrip()}\n")
    except OSError:
        pass


def open_folder(path):
    p = Path(str(path)).resolve()
    root = DEFAULT_DOCS_ROOT.resolve()
    if p != root and root not in p.parents:
        raise UserError("فقط پوشه‌های داخل docs باز می‌شوند.")
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        raise UserError("این پوشه وجود ندارد.")
    os.startfile(p)  # noqa: S606 (Windows Explorer)
    return {"ok": True}


class App:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.last_seen = time.time()
        self.server = None
        self.port = None


APP = App()

ROUTES = {
    ("GET", "/api/profiles"): lambda body: list_profiles(),
    ("GET", "/api/job"): lambda body: {"job": job_snapshot()},
    ("POST", "/api/test"): test_connection,
    ("POST", "/api/save"): save_profile,
    ("POST", "/api/delete"): delete_profile,
    ("GET", "/api/ai"): lambda body: ai_key_status(),
    ("POST", "/api/ai/save"): ai_key_save,
    ("POST", "/api/ai/delete"): ai_key_delete,
    ("POST", "/api/run"): start_job,
    ("POST", "/api/open"): lambda body: open_folder(body.get("path", "")),
    ("POST", "/api/ping"): lambda body: {"ok": True},
    ("POST", "/api/quit"): lambda body: quit_app(body),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "oradoc"

    def log_message(self, fmt, *args):  # request lines only ever go nowhere (bodies hold passwords)
        pass

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{APP.port}", f"localhost:{APP.port}")

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _page(self):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        if not hmac.compare_digest((q.get("t") or [""])[0], APP.token):
            msg = "<meta charset=utf-8><p dir=rtl style='font-family:Tahoma'>این پنجره قدیمی است و دیگر معتبر نیست. اطلس را دوباره با Atlas.cmd یا میانبر «Atlas» باز کنید؛ صفحه درست خودش باز می‌شود.</p>"
            return self._send(403, msg.encode("utf-8"), "text/html; charset=utf-8")
        html = PAGE.read_text(encoding="utf-8").replace("__ORADOC_TOKEN__", APP.token)
        self.send_response(200)
        data = html.encode("utf-8")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?", 1)[0]
        if method == "GET" and path == "/":
            return self._page()
        if not hmac.compare_digest(self.headers.get("X-Oradoc-Token", ""), APP.token):
            return self._send(403, {"error": "forbidden"})
        route = ROUTES.get((method, path))
        if not route:
            return self._send(404, {"error": "not found"})
        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY or "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._send(400, {"error": "درخواست نامعتبر"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, {"error": "درخواست نامعتبر"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "درخواست نامعتبر"})
        APP.last_seen = time.time()
        try:
            return self._send(200, route(body))
        except UserError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception:
            _write_log(f"{method} {path}\n{traceback.format_exc()}")
            return self._send(500, {"error": "خطای داخلی برنامه؛ جزئیات در logs\\oradoc_app.log"})
        finally:
            body.pop("password", None)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def _idle_watch():
    while True:
        time.sleep(30)
        if time.time() - APP.last_seen > IDLE_SECONDS and not job_running():
            APP.server.shutdown()
            return


class AtlasServer(ThreadingHTTPServer):
    """Binds its port exclusively. HTTPServer's default SO_REUSEADDR lets a second process bind the
    same port on Windows; requests then reach the older instance, which rejects the new token."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port=PREFERRED_PORT):
    try:
        server = AtlasServer(("127.0.0.1", port), Handler)
    except OSError:
        server = AtlasServer(("127.0.0.1", 0), Handler)  # preferred port busy: any free port
    APP.server, APP.port = server, server.server_address[1]
    return server


def app_url(port, token):
    return f"http://127.0.0.1:{port}/?t={token}"


def _call(port, token, method, path):
    """Status of one request to a local Atlas instance (JSON body for POST)."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    headers = {"Host": f"127.0.0.1:{port}", "X-Oradoc-Token": token}
    body = None
    if method == "POST":
        headers["Content-Type"], body = "application/json", "{}"
    c.request(method, path, body=body, headers=headers)
    return c.getresponse().status


def running_instance():
    """URL of an Atlas already running this same code from this folder (per logs/instance.json), or None.

    An instance running older code is asked to quit (it refuses while a job runs); either way a new
    instance is started, on another port if the old one still holds it."""
    try:
        info = json.loads(INSTANCE_PATH.read_text(encoding="utf-8"))
        port, token = int(info["port"]), str(info["token"])
        if _call(port, token, "GET", "/api/job") != 200:
            return None
        if info.get("version") == CODE_VERSION:
            return app_url(port, token)
        _call(port, token, "POST", "/api/quit")
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        pass
    return None


def quit_app(body):
    """Stop this instance (used when a newer version starts); refused while a job is running."""
    if job_running():
        raise UserError("یک عملیات در حال اجراست.")
    threading.Thread(target=APP.server.shutdown, daemon=True).start()
    return {"ok": True}


def _write_instance():
    INSTANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    INSTANCE_PATH.write_text(json.dumps({"port": APP.port, "token": APP.token, "pid": os.getpid(),
                                         "version": CODE_VERSION}), encoding="utf-8")


def _remove_instance():
    try:
        if json.loads(INSTANCE_PATH.read_text(encoding="utf-8")).get("token") == APP.token:
            INSTANCE_PATH.unlink()
    except (OSError, ValueError):
        pass


def main(open_browser=True):
    """Start Atlas, or (when it is already running from this folder) just open its page again."""
    url = running_instance()
    if url:
        if open_browser:
            webbrowser.open(url)
        return
    server = make_server()
    _write_instance()
    threading.Thread(target=_idle_watch, daemon=True).start()
    if open_browser:
        webbrowser.open(app_url(APP.port, APP.token))
    try:
        server.serve_forever()
    finally:
        server.server_close()
        _remove_instance()


if __name__ == "__main__":
    try:
        main(open_browser="--no-browser" not in sys.argv)
    except Exception:
        _write_log(traceback.format_exc())
        raise

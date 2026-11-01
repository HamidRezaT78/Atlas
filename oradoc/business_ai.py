"""Optional Claude enrichment of the business analysis (official anthropic SDK).

Sends only STRUCTURE (table/column names, types, nullability, keys, relationships, CHECK value lists and
recorded comments) plus the offline rule-based draft; never table rows. The API key lives in Windows
Credential Manager (service Atlas_Claude). Results are language-specific and cached by the caller.
"""
import json

import keyring

from .analysis import type_label
from .business import name_phrase

DEFAULT_MODEL = "claude-opus-5-5"
PRICES = {"claude-opus-5-5": (4.0, 20.0)}  # USD per million input / output tokens, for the cost line only
KEYRING_SERVICE, KEYRING_USER = "Atlas_Claude", "api_key"
PROMPT_VERSION = 1
MAX_TABLES_PER_CALL = 25
MAX_CHARS_PER_CALL = 60000
MAX_COLUMN_NOTES = 12

LANG_NAME = {"fa": "Persian (Farsi), formal and clear", "en": "English"}

SYSTEM = """You are a senior business analyst documenting an existing database for business stakeholders.
You receive only the database STRUCTURE (names, data types, keys, relationships, CHECK value lists, recorded
comments) and a draft produced by naming rules; no data rows. Infer what the business does with each table.

Rules:
- Write every text value in {language}. Keep table and column identifiers exactly as given (Latin, in backticks
  only if you quote them inside a sentence).
- Be concrete about the business meaning, but do not invent facts the structure does not support; when you
  infer, say so briefly (e.g. "probably" / «احتمالاً»).
- business_name: 2-5 words, the business concept the table holds (not a translation of the technical suffix).
- description: 1-3 sentences: what one row represents, who/what creates it, and how it is used.
- columns: only columns whose business meaning is not obvious from their name (at most {max_cols}); skip
  ID/audit columns.
- The draft's roles and relations come from rules and can be wrong; correct them in your text when the
  structure clearly says otherwise."""

TABLES_SCHEMA = {
    "type": "object",
    "properties": {"tables": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "table": {"type": "string"},
            "business_name": {"type": "string"},
            "description": {"type": "string"},
            "columns": {"type": "array", "items": {
                "type": "object",
                "properties": {"column": {"type": "string"}, "meaning": {"type": "string"}},
                "required": ["column", "meaning"], "additionalProperties": False}},
        },
        "required": ["table", "business_name", "description", "columns"], "additionalProperties": False}}},
    "required": ["tables"], "additionalProperties": False,
}

OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string"},
        "summary": {"type": "string"},
        "modules": {"type": "array", "items": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["key", "name", "description"], "additionalProperties": False}},
        "processes": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                           "tables": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "description", "tables"], "additionalProperties": False}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["domain", "summary", "modules", "processes", "questions"], "additionalProperties": False,
}


class AIError(Exception):
    """A message for the person, safe to show (no key, no connection secrets)."""


# ---------------------------------------------------------------------------
# API key (Windows Credential Manager)
# ---------------------------------------------------------------------------

def get_key():
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def set_key(key):
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)


def delete_key():
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


def client(key):
    import anthropic  # imported lazily: the offline analysis never needs it

    return anthropic.Anthropic(api_key=key, max_retries=4)


def check_key(key, model=DEFAULT_MODEL):
    """Validate a key without spending tokens (Models API)."""
    import anthropic

    try:
        client(key).models.retrieve(model)
    except anthropic.AuthenticationError:
        raise AIError("کلید API نامعتبر است.") from None
    except anthropic.PermissionDeniedError:
        raise AIError("این کلید به مدل مورد نیاز دسترسی ندارد.") from None
    except anthropic.APIConnectionError:
        raise AIError("اتصال به Anthropic برقرار نشد؛ اینترنت یا پروکسی را بررسی کنید.") from None
    except anthropic.APIStatusError as exc:
        raise AIError(f"خطای Anthropic ({exc.status_code}).") from None


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

def table_block(snap, biz, name):
    """Compact structure of one table for the prompt (no data)."""
    t, b = snap["tables"][name], biz["tables"][name]
    fk = {}
    for r in snap["relationships"]:
        if r["source_table"] == name:
            for c in r["source_columns"]:
                fk[c] = f"FK->{r['target_table'] or (r['target_owner'] + '.?')}"
    for i in biz["implicit_relations"]:
        if i["table"] == name:
            fk.setdefault(i["column"], f"implicit->{i['target']}")
    pk = next((c["columns"] for c in t["constraints"] if c["type"] == "P"), [])
    values = {c["column"]: c["params"].get("values") for c in b["columns"] if c["params"].get("values")}
    lines = [f"TABLE {name} | draft: role={b['role']}, module={b.get('module')}, name={name_phrase(name, 'en')}"
             + (f" | comment: {' '.join(t['comment'].split())}" if t["comment"] else "")]
    for c in t["columns"]:
        bits = [c["name"], type_label(c), "null" if c["nullable"] else "not null"]
        if c["name"] in pk:
            bits.append("PK")
        if c["name"] in fk:
            bits.append(fk[c["name"]])
        if c.get("identity"):
            bits.append("identity")
        if c.get("virtual"):
            bits.append("computed")
        if c["default"]:
            bits.append(f"default={str(c['default'])[:40]}")
        if c["name"] in values:
            bits.append("values=" + "|".join(values[c["name"]])[:120])
        if c.get("comment"):
            bits.append("comment=" + " ".join(c["comment"].split())[:150])
        lines.append("  - " + " ".join(bits))
    return "\n".join(lines)


def batches(snap, biz):
    """Tables grouped by module, cut to MAX_TABLES_PER_CALL / MAX_CHARS_PER_CALL."""
    out, cur, size = [], [], 0
    order = [t for m in biz["modules"] for t in m["tables"]]
    order += [t for t in sorted(biz["tables"]) if t not in order]
    for name in order:
        block = table_block(snap, biz, name)
        if cur and (len(cur) >= MAX_TABLES_PER_CALL or size + len(block) > MAX_CHARS_PER_CALL):
            out.append(cur)
            cur, size = [], 0
        cur.append((name, block))
        size += len(block)
    if cur:
        out.append(cur)
    return out


def overview_payload(snap, biz, tables_ai):
    lines = [f"SCHEMA {snap['schema']}: {len(biz['tables'])} tables.", "", "MODULES (key: tables with business names):"]
    for m in biz["modules"]:
        items = ", ".join(f"{t} ({(tables_ai.get(t) or {}).get('business_name') or name_phrase(t, 'en')}; "
                          f"{biz['tables'][t]['role']})" for t in m["tables"])
        lines.append(f"- {m['key']}: {items}")
    lines += ["", "PATTERNS FOUND BY RULES:"]
    for p in biz["processes"]:
        if p["code"] != "proc_lifecycle":
            lines.append(f"- {p['code']}: {', '.join(p['tables'])}")
    lines += ["", "TABLE DESCRIPTIONS:"]
    for t in sorted(tables_ai):
        lines.append(f"- {t}: {tables_ai[t].get('description', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

def _call(cl, model, lang, schema, content, usage):
    import anthropic

    try:
        resp = cl.beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # a declined request is retried server-side on Anthropic's recommended model
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            system=SYSTEM.format(language=LANG_NAME[lang], max_cols=MAX_COLUMN_NOTES),
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        raise AIError("کلید API نامعتبر است.") from None
    except anthropic.PermissionDeniedError:
        raise AIError("این کلید اجازه استفاده از مدل را ندارد.") from None
    except anthropic.RateLimitError:
        raise AIError("محدودیت نرخ درخواست Anthropic؛ کمی بعد دوباره امتحان کنید.") from None
    except anthropic.APIConnectionError:
        raise AIError("اتصال به Anthropic برقرار نشد؛ اینترنت یا پروکسی را بررسی کنید.") from None
    except anthropic.APIStatusError as exc:
        raise AIError(f"خطای Anthropic ({exc.status_code}): {getattr(exc, 'message', '')}"[:300]) from None
    u = resp.usage
    usage["requests"] += 1
    usage["input_tokens"] += u.input_tokens or 0
    usage["output_tokens"] += u.output_tokens or 0
    if resp.stop_reason == "refusal":
        return None, "refusal"
    if resp.stop_reason == "max_tokens":
        return None, "max_tokens"
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text), None
    except ValueError:
        return None, "invalid_json"


def cost(usage, model=DEFAULT_MODEL):
    pin, pout = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return round(usage["input_tokens"] / 1e6 * pin + usage["output_tokens"] / 1e6 * pout, 4)


def enrich(snap, biz, *, key, lang="fa", model=DEFAULT_MODEL, log=print):
    """{"model", "lang", "tables": {T: {...}}, "modules": {key: {...}}, "processes", "questions", "domain",
    "summary", "usage", "warnings"}; raises AIError for problems the person must fix (key, network)."""
    cl = client(key)
    usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
    tables_ai, warnings = {}, []
    queue = [list(b) for b in batches(snap, biz)]
    total = len(queue)
    done = 0
    while queue:
        batch = queue.pop(0)
        names = [n for n, _ in batch]
        content = ("Describe these tables. Return one entry per table, using the exact table names.\n\n"
                   + "\n\n".join(block for _, block in batch))
        data, problem = _call(cl, model, lang, TABLES_SCHEMA, content, usage)
        if problem == "max_tokens" and len(batch) > 1:
            half = len(batch) // 2
            queue[:0] = [batch[:half], batch[half:]]
            total += 1
            continue
        done += 1
        if problem:
            warnings.append(f"{problem}: {', '.join(names)}")
            log(f"دسته {done}/{total}: پاسخ قابل استفاده نبود ({problem})؛ این جدول‌ها فقط با قواعد شرح داده می‌شوند.")
            continue
        for item in data.get("tables", []):
            if item.get("table") in names:
                tables_ai[item["table"]] = {
                    "business_name": item["business_name"].strip(),
                    "description": item["description"].strip(),
                    "columns": {c["column"]: c["meaning"].strip() for c in item.get("columns", [])
                                if c.get("column") in {x["name"] for x in snap["tables"][item["table"]]["columns"]}},
                }
        log(f"دسته {done}/{total}: {len(names)} جدول — تاکنون حدود ${cost(usage, model)}")
    data, problem = _call(cl, model, lang, OVERVIEW_SCHEMA, overview_payload(snap, biz, tables_ai), usage)
    result = {"model": model, "lang": lang, "tables": tables_ai, "modules": {}, "processes": [], "questions": [],
              "domain": "", "summary": "", "usage": usage, "warnings": warnings}
    if problem:
        warnings.append(f"overview: {problem}")
        log(f"جمع‌بندی کلی قابل استفاده نبود ({problem}).")
    else:
        keys = {m["key"] for m in biz["modules"]}
        result.update(
            domain=data["domain"].strip(), summary=data["summary"].strip(),
            modules={m["key"]: {"name": m["name"].strip(), "description": m["description"].strip()}
                     for m in data["modules"] if m["key"] in keys},
            processes=[{"name": p["name"].strip(), "description": p["description"].strip(),
                        "tables": [t for t in p["tables"] if t in biz["tables"]]} for p in data["processes"]],
            questions=[q.strip() for q in data["questions"] if q.strip()],
        )
    usage["cost_usd"] = cost(usage, model)
    log(f"غنی‌سازی تمام شد: {usage['requests']} درخواست، {usage['input_tokens']} توکن ورودی، "
        f"{usage['output_tokens']} توکن خروجی، حدود ${usage['cost_usd']}")
    return result

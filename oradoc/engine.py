"""End-to-end pipeline: collect (or load) → analyze → render → validate → write."""
import json
import shutil
from datetime import datetime
from pathlib import Path

from .analysis import analyze
from .collector import canonical_json, collect, fingerprint
from .config import PACKAGE_DIR, check_object_name, get_profile
from .i18n import AUDIENCES, DETAILS, LANGS
from .render import render_coverage, render_erd, render_markdown
from .validate import compute

DEFAULT_DOCS_ROOT = PACKAGE_DIR.parent / "docs"


def output_names(schema, lang, audience="technical"):
    suffix = "" if audience == "technical" else f".{audience}"
    return {
        "markdown": f"{schema}_Database_Documentation.{lang}{suffix}.md",
        "erd": f"{schema}_erd.mmd",
        "snapshot": f"{schema}_snapshot.json",
        "coverage": f"{schema}_coverage.{lang}{suffix}.json",
    }


def load_snapshot(path):
    snap = json.loads(Path(path).read_text(encoding="utf-8"))
    if snap.get("format") != 1:
        raise ValueError("Unsupported snapshot format.")
    if fingerprint(snap) != snap.get("fingerprint"):
        raise ValueError("Snapshot fingerprint does not match its content (file was modified).")
    return snap


def load_annotations(path):
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("tables", "columns"):
        for target, value in (data.get(key) or {}).items():
            if not isinstance(value, dict) or not isinstance(value.get("text"), str):
                raise ValueError(f"Annotation {key}.{target} must be an object with a 'text' string.")
    return {"tables": data.get("tables") or {}, "columns": data.get("columns") or {}}


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


class OutputConflict(Exception):
    """Existing output files would change; nothing has been written."""

    def __init__(self, conflicts):
        self.conflicts = [str(p) for p in conflicts]
        super().__init__(
            "existing output files differ from the new output; nothing was written: "
            + ", ".join(self.conflicts)
            + ". Use a new output directory, or pass --overwrite to replace them "
              "(the current versions are copied to <out>/_backup/<timestamp>/ first).")


def write_outputs(out, files, *, overwrite=False):
    """Write {path: text} with a preflight check, so existing outputs never change silently.

    A file whose current content is byte-identical to the new content is left untouched.
    Any other existing file is a conflict: without overwrite, OutputConflict is raised
    before anything is written; with overwrite, each conflicting file is first copied to
    <out>/_backup/<YYYYmmdd-HHMMSS>/ and then replaced.
    """
    out = Path(out)
    plan, unchanged, conflicts = {}, [], []
    for path, text in files.items():
        path = Path(path)
        if path.exists():
            if path.read_bytes() == text.encode("utf-8"):
                unchanged.append(path)
                continue
            conflicts.append(path)
        plan[path] = text
    if conflicts and not overwrite:
        raise OutputConflict(conflicts)

    backup_dir = None
    if conflicts:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = out / "_backup" / stamp
        n = 1
        while backup_dir.exists():
            backup_dir = out / "_backup" / f"{stamp}-{n}"
            n += 1
        backup_dir.mkdir(parents=True)
        for path in conflicts:
            shutil.copy2(path, backup_dir / path.name)
    for path, text in plan.items():
        write_text(path, text)
    return {
        "written": sorted(str(p) for p in plan),
        "unchanged": sorted(str(p) for p in unchanged),
        "replaced": sorted(str(p) for p in conflicts),
        "backup_dir": str(backup_dir) if backup_dir else None,
    }


def build(snap, *, lang, detail, annotations=None, audience="technical"):
    """Pure rendering step: same snapshot + options -> identical outputs."""
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}")
    if detail not in DETAILS:
        raise ValueError(f"detail must be one of {DETAILS}")
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {AUDIENCES}")
    names = output_names(snap["schema"], lang, audience)
    findings = analyze(snap)
    erd_text, erd_emitted = render_erd(snap)
    doc, md_emitted = render_markdown(snap, findings, lang=lang, detail=detail,
                                      erd_filename=names["erd"], annotations=annotations, audience=audience)
    coverage = compute(snap, md_emitted, erd_emitted, detail, annotations)
    markdown = render_coverage(doc, coverage)
    return {"names": names, "markdown": markdown, "erd": erd_text, "coverage": coverage, "findings": findings}


def generate_business(*, snapshot_path, out_dir=None, lang="fa", ai=False, ai_key=None, model=None,
                      overwrite=False, log=print):
    """Business-analysis document (rules, optionally enriched by Claude) from a saved snapshot.

    The Claude result is cached next to the document (<SCHEMA>_business_ai.<lang>.json) and reused while the
    snapshot fingerprint, model and prompt version are unchanged. An AI failure falls back to rules only."""
    from . import business_ai
    from .business import analyze_business
    from .business_render import business_names, render_business

    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}")
    snap = load_snapshot(snapshot_path)
    out = Path(out_dir) if out_dir else Path(snapshot_path).parent
    names = business_names(snap["schema"], lang)
    biz = analyze_business(snap)
    files, ai_result, warnings = {}, None, []
    if ai:
        model = model or business_ai.DEFAULT_MODEL
        cache = out / names["ai"]
        cached = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
        if (cached.get("fingerprint") == snap["fingerprint"] and cached.get("prompt_version") == business_ai.PROMPT_VERSION
                and cached.get("result", {}).get("model") == model):
            ai_result = cached["result"]
            log("نتیجه قبلی هوش مصنوعی برای همین ساختار دوباره استفاده شد (بدون هزینه).")
        else:
            key = ai_key or business_ai.get_key()
            if not key:
                warnings.append("کلید Claude API ذخیره نشده است؛ تحلیل فقط با قواعد انجام شد.")
            else:
                try:
                    ai_result = business_ai.enrich(snap, biz, key=key, lang=lang, model=model, log=log)
                    files[cache] = canonical_json({"fingerprint": snap["fingerprint"],
                                                   "prompt_version": business_ai.PROMPT_VERSION,
                                                   "result": ai_result}) + "\n"
                except business_ai.AIError as exc:
                    warnings.append(f"هوش مصنوعی: {exc} تحلیل فقط با قواعد انجام شد.")
        if ai_result and ai_result.get("warnings"):
            warnings.append(f"هوش مصنوعی: {len(ai_result['warnings'])} دسته فقط با قواعد شرح داده شد.")
    for w in warnings:
        log(w)
    markdown, coverage = render_business(snap, biz, lang=lang, ai=ai_result)
    files[out / names["markdown"]] = markdown
    write = write_outputs(out, files, overwrite=overwrite)
    return {
        "out_dir": str(out), "markdown": str(out / names["markdown"]), "write": write, "coverage": coverage,
        "passed": coverage["passed"], "warnings": warnings, "summary": biz["summary"],
        "ai": {"model": ai_result["model"], "usage": ai_result.get("usage")} if ai_result else None,
    }


def generate(*, profile=None, schema=None, lang="fa", detail="standard", out_dir=None,
             snapshot_path=None, annotations_path=None, config_path=None, overwrite=False, audience="technical"):
    if snapshot_path:
        snap = load_snapshot(snapshot_path)
        engine = snap.get("engine", "oracle")
        if schema and check_object_name(schema, engine).casefold() != snap["schema"].casefold():
            raise ValueError("Requested schema does not match the snapshot.")
    else:
        prof = get_profile(profile, path=config_path)
        snap = collect(prof, schema)
    annotations = load_annotations(annotations_path)
    result = build(snap, lang=lang, detail=detail, annotations=annotations, audience=audience)

    out = Path(out_dir) if out_dir else DEFAULT_DOCS_ROOT / snap["profile"] / snap["schema"]
    names = result["names"]
    write = write_outputs(out, {
        out / names["snapshot"]: canonical_json(snap) + "\n",
        out / names["erd"]: result["erd"],
        out / names["markdown"]: result["markdown"],
        out / names["coverage"]: canonical_json(result["coverage"]) + "\n",
    }, overwrite=overwrite)
    return {
        "out_dir": str(out),
        "files": {k: str(out / v) for k, v in names.items()},
        "write": write,
        "passed": result["coverage"]["passed"],
        "coverage": result["coverage"],
        "fingerprint": snap["fingerprint"],
        "tables": len(snap["tables"]),
        "columns": sum(len(t["columns"]) for t in snap["tables"].values()),
    }

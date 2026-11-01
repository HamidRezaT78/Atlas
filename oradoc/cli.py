"""Command line: python -m oradoc <command> ...

  profiles                         list configured profiles (no connection details printed)
  auth --profile P                 store the password in Windows Credential Manager (interactive)
  snapshot --profile P --schema S  collect metadata only, write <out>/<S>_snapshot.json
  generate [options]               full pipeline (collect or --from-snapshot, render, validate)
  run-job JOB.json                 generate from a job file (as produced by the Artifact launcher)
  business --from-snapshot S.json  business-analysis document (rules; --ai adds Claude enrichment)
  ai-key --set | --check | --delete  Claude API key in Windows Credential Manager (for business --ai)

generate --audience client writes <S>_Database_Documentation.<lang>.client.md: the same per-table
detail without the label legend, keys/indexes summaries, structural analysis, DBA review, open
questions or coverage report (coverage is still validated and written to the .client.json file).

Existing outputs are never replaced silently: an existing file whose content would change stops
the run before anything is written. Identical files are left as they are. Pass --overwrite (or
"overwrite": true in a job file) to replace them; the current versions are copied to
<out>/_backup/<timestamp>/ first.

Exit codes: 0 = documented and validated, 2 = written but coverage validation failed,
1 = error or output conflict (nothing written).
"""
import argparse
import getpass
import json
import sys
from pathlib import Path

from .collector import canonical_json, collect
from .config import get_profile, load_config
from .engine import DEFAULT_DOCS_ROOT, OutputConflict, generate, generate_business, write_outputs
from .i18n import AUDIENCES, DETAILS, LANGS

JOB_KEYS = {"profile", "schema", "lang", "detail", "out_dir", "annotations", "from_snapshot", "overwrite", "audience",
            "business", "business_ai"}


def cmd_profiles(args):
    cfg = load_config(args.config)
    for name, p in sorted(cfg["profiles"].items()):
        mark = " (default)" if name == cfg["default_profile"] else ""
        print(f"{name}{mark}: user={p.username} schemas={', '.join(p.allowed_schemas)} default_schema={p.default_schema}")
    return 0


def cmd_auth(args):
    import keyring

    prof = get_profile(args.profile, path=args.config)
    password = getpass.getpass(f"Password for {prof.username} (profile {prof.name}): ")
    if not password:
        print("Empty password; nothing stored.", file=sys.stderr)
        return 1
    keyring.set_password(prof.keyring_service, prof.username, password)
    print(f"Stored in Windows Credential Manager under service {prof.keyring_service!r}.")
    return 0


def cmd_snapshot(args):
    prof = get_profile(args.profile, path=args.config)
    snap = collect(prof, args.schema)
    out = Path(args.out) if args.out else DEFAULT_DOCS_ROOT / snap["profile"] / snap["schema"]
    path = out / f"{snap['schema']}_snapshot.json"
    write = write_outputs(out, {path: canonical_json(snap) + "\n"}, overwrite=args.overwrite)
    failed = [k for k, v in snap["sections"].items() if v["status"] == "failed"]
    print(f"snapshot: {path}  tables={len(snap['tables'])} fingerprint={snap['fingerprint']}")
    if write["unchanged"]:
        print("  unchanged (identical content already present)")
    if write["backup_dir"]:
        print(f"  previous version backed up to: {write['backup_dir']}")
    for k in failed:
        print(f"  FAILED section {k}: {snap['sections'][k]['error']}")
    return 2 if failed else 0


def report(result):
    cov = result["coverage"]
    print(f"output: {result['out_dir']}")
    for kind, path in result["files"].items():
        print(f"  {kind}: {path}")
    write = result["write"]
    print(f"files written={len(write['written'])} unchanged={len(write['unchanged'])} "
          f"replaced={len(write['replaced'])}")
    if write["backup_dir"]:
        print(f"  previous versions backed up to: {write['backup_dir']}")
    print(f"tables={result['tables']} columns={result['columns']} fingerprint={result['fingerprint']}")
    for key, item in cov["items"].items():
        state = "ok" if item["ok"] else "INCOMPLETE"
        print(f"  {key}: discovered={item['discovered']} independent={item['independent']} "
              f"document={item['in_document']} erd={item['in_erd']} -> {state}")
        if item["missing"]:
            print(f"    missing: {', '.join(item['missing'][:20])}")
    for k in cov["failed_sections"]:
        print(f"  FAILED section {k}: {cov['sections'][k]['error']}")
    print("VALIDATION: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 2


def cmd_generate(args):
    result = generate(profile=args.profile, schema=args.schema, lang=args.lang, detail=args.detail,
                      out_dir=args.out, snapshot_path=args.from_snapshot,
                      annotations_path=args.annotations, config_path=args.config,
                      overwrite=args.overwrite, audience=args.audience)
    return report(result)


def cmd_run_job(args):
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    unknown = set(job) - JOB_KEYS
    if unknown:
        raise ValueError(f"Unknown job keys: {sorted(unknown)} (allowed: {sorted(JOB_KEYS)})")
    if job.get("lang", "fa") not in LANGS or job.get("detail", "standard") not in DETAILS:
        raise ValueError("Invalid lang or detail in job file.")
    if not all(isinstance(job.get(k, False), bool) for k in ("business", "business_ai")):
        raise ValueError("'business' and 'business_ai' in a job file must be true or false.")
    if not isinstance(job.get("overwrite", False), bool):
        raise ValueError("'overwrite' in a job file must be true or false.")
    if job.get("audience", "technical") not in AUDIENCES:
        raise ValueError(f"'audience' in a job file must be one of {AUDIENCES}.")
    result = generate(profile=job.get("profile"), schema=job.get("schema"), lang=job.get("lang", "fa"),
                      detail=job.get("detail", "standard"), out_dir=job.get("out_dir") or None,
                      snapshot_path=job.get("from_snapshot") or None,
                      annotations_path=job.get("annotations") or None, config_path=args.config,
                      overwrite=job.get("overwrite", False), audience=job.get("audience", "technical"))
    code = report(result)
    if job.get("business") or job.get("business_ai"):
        biz = generate_business(snapshot_path=result["files"]["snapshot"], out_dir=result["out_dir"],
                                lang=job.get("lang", "fa"), ai=bool(job.get("business_ai")),
                                overwrite=job.get("overwrite", False))
        print(f"business: {biz['markdown']}  coverage={'PASS' if biz['passed'] else 'FAIL'}")
        code = code or (0 if biz["passed"] else 2)
    return code


def cmd_business(args):
    result = generate_business(snapshot_path=args.from_snapshot, out_dir=args.out, lang=args.lang, ai=args.ai,
                               model=args.model, overwrite=args.overwrite)
    print(f"business: {result['markdown']}")
    s = result["summary"]
    print(f"tables={s['tables']} modules={s['modules']} processes={s['processes']} implicit={s['implicit']} "
          f"sensitive={s['sensitive']} roles={s['roles']}")
    if result["ai"]:
        print(f"ai: {result['ai']['model']} usage={result['ai']['usage']}")
    for w in result["warnings"]:
        print(f"  warning: {w}")
    print("COVERAGE: " + ("PASS" if result["passed"] else "FAIL " + ", ".join(result["coverage"]["missing"][:20])))
    return 0 if result["passed"] else 2


def cmd_ai_key(args):
    from . import business_ai

    if args.delete:
        business_ai.delete_key()
        print("Claude API key removed from Windows Credential Manager.")
        return 0
    if args.set:
        key = getpass.getpass("Claude API key: ").strip()
        if not key:
            print("Empty key; nothing stored.", file=sys.stderr)
            return 1
        business_ai.check_key(key)
        business_ai.set_key(key)
        print(f"Stored in Windows Credential Manager under service {business_ai.KEYRING_SERVICE!r}.")
        return 0
    key = business_ai.get_key()
    if not key:
        print("No Claude API key stored.")
        return 1
    business_ai.check_key(key)
    print("Stored Claude API key is valid.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oradoc", description="Read-only Oracle schema documentation.")
    ap.add_argument("--config", help="profiles.toml path (default: ORADOC_CONFIG or config/profiles.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("profiles").set_defaults(fn=cmd_profiles)

    p = sub.add_parser("auth")
    p.add_argument("--profile", required=True)
    p.set_defaults(fn=cmd_auth)

    p = sub.add_parser("snapshot")
    p.add_argument("--profile")
    p.add_argument("--schema")
    p.add_argument("--out", help="output directory")
    p.add_argument("--overwrite", action="store_true",
                   help="replace an existing, different snapshot (backed up to <out>/_backup/<timestamp>/)")
    p.set_defaults(fn=cmd_snapshot)

    p = sub.add_parser("generate")
    p.add_argument("--profile")
    p.add_argument("--schema")
    p.add_argument("--lang", choices=LANGS, default="fa")
    p.add_argument("--detail", choices=DETAILS, default="standard")
    p.add_argument("--out", help="output directory (default docs/<profile>/<schema>)")
    p.add_argument("--from-snapshot", help="render offline from a saved snapshot JSON")
    p.add_argument("--annotations", help="JSON file of user-provided descriptions")
    p.add_argument("--audience", choices=AUDIENCES, default="technical",
                   help="technical (complete) or client (no legend, analysis, DBA review, questions, coverage)")
    p.add_argument("--overwrite", action="store_true",
                   help="replace existing, different output files (backed up to <out>/_backup/<timestamp>/)")
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("business")
    p.add_argument("--from-snapshot", required=True, help="saved snapshot JSON")
    p.add_argument("--lang", choices=LANGS, default="fa")
    p.add_argument("--out", help="output directory (default: the snapshot's folder)")
    p.add_argument("--ai", action="store_true", help="enrich with Claude (needs: oradoc ai-key --set)")
    p.add_argument("--model", help="Claude model id (default claude-opus-5-5)")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(fn=cmd_business)

    p = sub.add_parser("ai-key")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--set", action="store_true", help="ask for the key and store it (it is checked first)")
    g.add_argument("--check", action="store_true", help="check the stored key without spending tokens")
    g.add_argument("--delete", action="store_true")
    p.set_defaults(fn=cmd_ai_key)

    p = sub.add_parser("run-job")
    p.add_argument("job")
    p.set_defaults(fn=cmd_run_job)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except OutputConflict as exc:
        print("error: output conflict; nothing was written. These existing files would change:", file=sys.stderr)
        for path in exc.conflicts:
            print(f"  {path}", file=sys.stderr)
        print("Use a new --out directory, or re-run with --overwrite to replace them "
              "(current versions are backed up to <out>/_backup/<timestamp>/ first).", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

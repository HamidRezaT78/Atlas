"""Publish an oradoc run folder as the three Persian deliverables (Word technical, Word client, draw.io ERD).

Usage (from the project folder):
    .\\.venv\\Scripts\\python.exe tools\\publish\\publish.py --run <run folder> --service SALES_DB --profile sales_db

Writes three files to docs\\<profile>\\<SERVICE>\\ (or --out-dir):
    <SERVICE>_<yyyyMMdd>_dev.docx, <SERVICE>_<yyyyMMdd>_client.docx, <SERVICE>_<yyyyMMdd>_erd.drawio
plus <SERVICE>_<yyyyMMdd>_business.docx when the run folder has <SCHEMA>_Business_Analysis.fa.md.
Fully offline (vendored Mermaid in headless Chrome with host resolution blocked; Word via COM), no database
access. Never overwrites: any existing target stops the run before anything is built. Intermediate files
(raw docx, PNG, Chrome profile) stay in a temporary work folder that is removed after a successful run.
The files are delivered only when every content check passes. Exit code: 0 PASS, 1 FAIL or error.
"""
import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import docx_check  # noqa: E402
import make_drawio  # noqa: E402
import md2docx  # noqa: E402
import render_erd  # noqa: E402

LANG = "fa"


def one(run, pattern):
    found = sorted(run.glob(pattern))
    if len(found) != 1:
        raise SystemExit(f"expected exactly one {pattern} in {run}, found {len(found)}")
    return found[0]


def mermaid_block(md_path):
    m = re.search(r"^```mermaid\n(.*?)^```", md_path.read_text(encoding="utf-8"), re.S | re.M)
    if not m:
        raise SystemExit(f"no ```mermaid block in {md_path}")
    return m.group(1)


def powershell(script, *args):
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(HERE / script)]
    p = subprocess.run(cmd + [str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout + p.stderr).rstrip()
    if out:
        print(out)
    return p.returncode == 0


def check_drawio(path, snap_path):
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    cells = ET.parse(path).getroot().iter("mxCell")
    ids = [c.get("id", "") for c in cells]
    tables = sum(i.startswith("t_") for i in ids)
    edges = sum(i.startswith("e_") for i in ids)
    want_edges = sum(1 for r in snap["relationships"] if not r["external"] and r["target_table"])
    ok = tables == len(snap["tables"]) and edges == want_edges
    print(f"== {path.name}\n   tables: snapshot={len(snap['tables'])} drawio={tables}  relationships: snapshot={want_edges} drawio={edges}")
    print("   RESULT:", "PASS" if ok else "FAIL")
    return ok


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, type=Path, help="oradoc run folder (fa technical + fa client output)")
    ap.add_argument("--service", required=True, help="deliverable name, e.g. SALES_DB")
    ap.add_argument("--profile", required=True, help="connection profile folder under docs, e.g. sales_db")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y%m%d"), help="yyyyMMdd in file names (default today)")
    ap.add_argument("--out-dir", type=Path, help="target folder (default docs\\<profile>\\<SERVICE>)")
    ap.add_argument("--keep-work", action="store_true", help="keep the temporary work folder")
    a = ap.parse_args()
    if not re.fullmatch(r"\d{8}", a.date):
        raise SystemExit("--date must be yyyyMMdd")

    run = a.run.resolve()
    snap = one(run, "*_snapshot.json")
    tech_md = one(run, f"*_Database_Documentation.{LANG}.md")
    client_md = one(run, f"*_Database_Documentation.{LANG}.client.md")
    erd_mmd = one(run, "*_erd.mmd")
    business = sorted(run.glob(f"*_Business_Analysis.{LANG}.md"))
    if len(business) > 1:
        raise SystemExit(f"expected at most one *_Business_Analysis.{LANG}.md in {run}, found {len(business)}")
    business_md = business[0] if business else None
    schema = json.loads(snap.read_text(encoding="utf-8"))["schema"]

    out_dir = (a.out_dir or PROJECT / "docs" / a.profile / a.service).resolve()
    stem = f"{a.service}_{a.date}"
    names = {"dev": f"{stem}_dev.docx", "client": f"{stem}_client.docx", "erd": f"{stem}_erd.drawio"}
    if business_md:
        names["business"] = f"{stem}_business.docx"
    conflicts = [out_dir / n for n in names.values() if (out_dir / n).exists()]
    if conflicts:
        print("STOP: these files already exist and are never overwritten:")
        for c in conflicts:
            print("   ", c)
        return 1

    work = Path(tempfile.mkdtemp(prefix="oradoc_publish_"))
    print(f"run={run}\nschema={schema} service={a.service} date={a.date}\nwork={work}\nout={out_dir}")

    print("\n[1/5] offline Mermaid render")
    rel_mmd = work / "relationships.mmd"
    rel_mmd.write_text(mermaid_block(client_md), encoding="utf-8")
    rel = render_erd.render(rel_mmd, work, scale=2, name="relationships")
    rel_png = work / "relationships.png"
    rel_png.write_bytes(rel["png_bytes"])
    print(f"   relationship diagram: entities={rel['entityNodes']} png={rel['pngWidth']}x{rel['pngHeight']}")
    full = render_erd.render(erd_mmd, work, scale=0, name="full")
    print(f"   full ERD layout: node boxes={len(full['nodes'])}")
    if business_md:
        mod_mmd = work / "modules.mmd"
        mod_mmd.write_text(mermaid_block(business_md), encoding="utf-8")
        mod_png = work / "modules.png"
        mod_png.write_bytes(render_erd.render(mod_mmd, work, scale=2, name="modules")["png_bytes"])
        print("   business module map rendered")

    print("\n[2/5] Word documents")
    built = work / "built"
    built.mkdir()
    md2docx.convert(tech_md, work / "raw_dev.docx", LANG, schema)
    md2docx.convert(client_md, work / "raw_client.docx", LANG, schema, img=rel_png)
    ok = powershell("word_finish.ps1", work / "raw_dev.docx", built / names["dev"])
    ok = powershell("word_finish.ps1", work / "raw_client.docx", built / names["client"]) and ok
    if business_md:
        md2docx.convert(business_md, work / "raw_business.docx", LANG, schema, img=mod_png,
                        header="تحلیل بیزنسی {schema}")
        ok = powershell("word_finish.ps1", work / "raw_business.docx", built / names["business"]) and ok
    if not ok:
        print(f"FAIL: Word finishing failed; work folder kept: {work}")
        return 1

    print("\n[3/5] draw.io")
    print("  ", make_drawio.build(snap, full["nodes"], erd_mmd, built / names["erd"]))

    print("\n[4/5] content checks")
    results = [
        docx_check.check(tech_md, built / names["dev"], LANG),
        docx_check.check(client_md, built / names["client"], LANG, mermaid_image=True),
        powershell("word_direction.ps1", built / names["dev"]),
        powershell("word_direction.ps1", built / names["client"]),
        check_drawio(built / names["erd"], snap),
    ]
    if business_md:
        results += [docx_check.check(business_md, built / names["business"], LANG, mermaid_image=True),
                    powershell("word_direction.ps1", built / names["business"])]
    if not all(results):
        print(f"\nFAIL: {results.count(False)} check(s) failed; nothing delivered. Work folder kept: {work}")
        return 1

    print("\n[5/5] deliver")
    out_dir.mkdir(parents=True, exist_ok=True)
    for n in names.values():
        with open(built / n, "rb") as src, open(out_dir / n, "xb") as dst:  # "x": never overwrite
            shutil.copyfileobj(src, dst)
        print("   wrote", out_dir / n)
    if a.keep_work:
        print("   work folder kept:", work)
    else:
        shutil.rmtree(work, ignore_errors=True)
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

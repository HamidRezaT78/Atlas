"""Assemble the MCP bundle (.mcpb) from mcpb-src/, the oradoc package and the sample profile.

Usage: python tools/build_mcpb.py
Output: dist/atlas-db-docs-<version>.mcpb (existing bundles are never overwritten).
Only config/profiles.example.toml is packaged, never your own config/profiles.toml, so no address,
username or secret of yours can end up in a bundle. Real profiles are chosen in the extension settings.
"""
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "mcpb-src"
STAGE = ROOT / "build" / "mcpb"
DIST = ROOT / "dist"


def main():
    sys.path.insert(0, str(ROOT))
    from oradoc.config import load_config

    sample = ROOT / "config" / "profiles.example.toml"
    load_config(sample)  # raises on forbidden keys

    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    out = DIST / f"atlas-db-docs-{version}.mcpb"
    if out.exists():
        sys.exit(f"{out} already exists; bump the version in mcpb-src/manifest.json first.")

    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "server").mkdir(parents=True)
    shutil.copy2(SRC / "manifest.json", STAGE / "manifest.json")
    shutil.copy2(SRC / "pyproject.toml", STAGE / "pyproject.toml")
    shutil.copy2(SRC / "server" / "oracle_mcp.py", STAGE / "server" / "oracle_mcp.py")
    shutil.copy2(sample, STAGE / "server" / "profiles.toml")
    shutil.copytree(ROOT / "oradoc", STAGE / "server" / "oradoc",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "webapp.py", "business*.py"))  # local app only

    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(STAGE.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(STAGE).as_posix())
    print(out)
    with zipfile.ZipFile(out) as z:
        for info in z.infolist():
            print(f"  {info.filename} {info.file_size}")


if __name__ == "__main__":
    main()

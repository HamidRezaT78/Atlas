"""Build the GitHub Release assets in dist/ (git ignores it):

    atlas-db-docs-<version>.mcpb    the Claude Desktop extension
    Atlas-Tools-<version>.zip       the standalone app with offline wheels for Python 3.11-3.14

Usage: python tools/build_release.py [--wheels <folder with existing wheels>]
Without --wheels the wheels are downloaded from PyPI. Only allowlisted paths go into the zip, and your own
config/profiles.toml is never among them. Existing assets are never overwritten.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PYTHONS = ("3.11", "3.12", "3.13", "3.14")
INCLUDE = ["oradoc", "ui", "tools/publish", "tools/vendor", "tests", "config/profiles.example.toml", "Setup.cmd",
           "Atlas.cmd", "requirements.txt", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md"]


def download_wheels(target):
    for version in PYTHONS:
        subprocess.run([sys.executable, "-m", "pip", "download", "-q", "--disable-pip-version-check",
                        "--only-binary=:all:", "--platform", "win_amd64", "--python-version", version,
                        "--implementation", "cp", "-d", str(target), "-r", str(ROOT / "requirements.txt")], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wheels", type=Path, help="use these wheels instead of downloading them")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from oradoc import __version__ as version

    out = DIST / f"Atlas-Tools-{version}.zip"
    if out.exists():
        sys.exit(f"{out} already exists; bump the version in oradoc/__init__.py first.")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_mcpb.py")], check=True)

    work = Path(tempfile.mkdtemp(prefix="atlas_release_"))
    try:
        wheels = args.wheels or work / "wheels"
        if not args.wheels:
            wheels.mkdir()
            download_wheels(wheels)
        files = []
        for rel in INCLUDE:
            p = ROOT / rel
            files += [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
        with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                if "__pycache__" not in f.parts:
                    z.write(f, f"Atlas/{f.relative_to(ROOT).as_posix()}")
            for w in sorted(wheels.glob("*.whl")):
                z.write(w, f"Atlas/wheels/{w.name}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(out)


if __name__ == "__main__":
    main()

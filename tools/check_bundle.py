"""Offline checks of a built bundle and of legacy-SQL parity. Never connects to Oracle.

Usage: python tools/check_bundle.py <path-to-.mcpb> [path-to-original-oracle_mcp.py]
"""
import ast
import importlib.util
import os
import sys
import tempfile
import zipfile
from pathlib import Path


def sql_strings(path):
    """String constants passed as the first argument of fetch_json(...) in the original server."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "fetch_json":
            out.append(node.args[0].value)
    return out


def main(bundle, original=None):
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from oradoc import queries

    legacy = [queries.LEGACY_LIST_TABLES, queries.LEGACY_DESCRIBE_TABLE, queries.LEGACY_LIST_CONSTRAINTS,
              queries.LEGACY_LIST_INDEXES, queries.LEGACY_LIST_RELATIONSHIPS]
    if original:
        orig = sql_strings(original)
        assert orig == legacy, "legacy SQL differs from the original server"
        print(f"legacy SQL parity: {len(orig)} statements identical")

    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(bundle) as z:
        names = z.namelist()
        z.extractall(tmp)
    for required in ("manifest.json", "pyproject.toml", "server/oracle_mcp.py", "server/profiles.toml",
                     "server/oradoc/__init__.py", "server/oradoc/queries.py"):
        assert required in names, f"missing {required}"
    text = "\n".join(z_name for z_name in names)
    assert ".pyc" not in text and "__pycache__" not in text
    profiles = (tmp / "server" / "profiles.toml").read_text(encoding="utf-8").lower()
    assert "password =" not in profiles and "pwd =" not in profiles
    assert "example.com" in profiles, "only the sample profile may be packaged"
    print(f"bundle layout ok: {len(names)} files, no bytecode, no password keys")

    # Import the server from the extracted bundle only (project root removed from sys.path).
    sys.path.remove(str(root))
    for m in [m for m in sys.modules if m == "oradoc" or m.startswith("oradoc.")]:
        del sys.modules[m]
    os.environ.pop("ORADOC_CONFIG", None)
    os.chdir(tmp)
    spec = importlib.util.spec_from_file_location("bundled_server", tmp / "server" / "oracle_mcp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert Path(sys.modules["oradoc"].__file__).resolve().is_relative_to(tmp.resolve()), "oradoc not loaded from bundle"
    tools = sorted(t.name for t in mod.mcp._tool_manager.list_tools())
    profile, owner = mod._profile_and_owner("")
    print(f"bundled server imports ok; tools={tools}")
    print(f"bundled profile={profile.name} default schema={owner} allowlist={profile.allowed_schemas}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

"""Exercise the MCP metadata tools against the live, allowlisted schema (dictionary views only).

Usage: python tools/probe_tools.py [schema]
Prints a per-tool summary for every table and stops on nothing: failures are listed at the end.
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("oracle_mcp", ROOT / "mcpb-src" / "server" / "oracle_mcp.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

schema = sys.argv[1] if len(sys.argv) > 1 else ""
tables = [r["table_name"] for r in json.loads(server.list_tables(schema))]
print(f"tables: {len(tables)}")

failures = []
stats = Counter()
samples = {}
for t in tables:
    for tool in ("get_comments", "get_column_defaults", "get_check_constraints", "get_index_expressions"):
        try:
            out = json.loads(getattr(server, tool)(t, schema))
        except Exception as exc:
            failures.append((t, tool, f"{type(exc).__name__}: {str(exc)[:200]}"))
            continue
        if tool == "get_comments":
            stats["tables_with_comment"] += out["table_comment"] is not None
            stats["columns_listed_in_comments"] += len(out["columns"])
            stats["columns_with_comment"] += sum(c["comments"] is not None for c in out["columns"])
        elif tool == "get_column_defaults":
            stats["columns_incl_hidden"] += len(out["columns"])
            stats["hidden_columns"] += sum(c["hidden_column"] == "YES" for c in out["columns"])
            stats["columns_with_default"] += sum(c["data_default"] is not None for c in out["columns"])
            stats[f"identity_info_{out['identity_info']}"] += 1
            for c in out["columns"]:
                if c["data_default"] is not None and "default" not in samples:
                    samples["default"] = (t, c["column_name"], c["data_default"])
        elif tool == "get_check_constraints":
            stats["check_constraints"] += len(out)
            stats["not_null_checks"] += sum(c["is_not_null"] for c in out)
            stats["checks_without_condition"] += sum(c["search_condition"] is None for c in out)
            for c in out:
                if not c["is_not_null"]:
                    samples.setdefault("checks", []).append((t, c["constraint_name"], c["columns"], c["search_condition"]))
        else:
            stats["fbi_columns"] += len(out)
            for r in out:
                samples.setdefault("fbi", []).append((t, r["index_name"], r["index_type"], r["column_name"], r["column_expression"]))

print("\n".join(f"{k}: {v}" for k, v in sorted(stats.items())))
print("sample default:", samples.get("default"))
print("non-NOT-NULL checks:")
for s in samples.get("checks", []):
    print("  ", s)
print("function-based index columns:")
for s in samples.get("fbi", []):
    print("  ", s)
print(f"failures: {len(failures)}")
for f in failures:
    print("  ", f)

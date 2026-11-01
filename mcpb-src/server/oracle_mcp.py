import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# In the bundle, oradoc/ sits next to this file; in the project checkout it is two levels up.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent.parent):
    if (_p / "oradoc" / "__init__.py").is_file() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break

from oradoc import mssql_queries, queries  # noqa: E402
from oradoc.config import get_profile  # noqa: E402
from oradoc.db import connect, fetch  # noqa: E402

APP_NAME = "Atlas Database Documentation"

mcp = FastMCP(APP_NAME)


def _profile_and_owner(schema):
    profile = get_profile(extra=[_HERE / "profiles.toml"])
    return profile, profile.check_schema(schema)


def q_for(profile):
    """Statement module for the profile's engine (Oracle keeps its original legacy SQL below)."""
    return mssql_queries if profile.engine == "sqlserver" else queries


def to_json(rows):
    return json.dumps(rows, default=str, ensure_ascii=False)


def run_for_table(schema, table_name, fn):
    """Validate schema (allowlist) and table (exists in that schema), then run fn on one connection."""
    profile, owner = _profile_and_owner(schema)
    q = q_for(profile)
    with connect(profile) as conn:
        table = q.table_exists(conn, owner, table_name)
        return fn(conn, owner, table, q)


@mcp.tool()
def list_tables(schema: str = "") -> str:
    """List tables in an allowlisted schema (Oracle or SQL Server profile); never reads table rows."""
    profile, owner = _profile_and_owner(schema)
    with connect(profile) as conn:
        if profile.engine == "sqlserver":
            return to_json(mssql_queries.legacy_list_tables(conn, owner))
        return to_json(fetch(conn, queries.LEGACY_LIST_TABLES, {"owner": owner}))


@mcp.tool()
def describe_table(table_name: str, schema: str = "") -> str:
    """List column names, types, sizes, precision, scale and nullability."""
    return run_for_table(schema, table_name, lambda conn, owner, table, q: to_json(
        q.legacy_describe_table(conn, owner, table) if q is mssql_queries else
        fetch(conn, queries.LEGACY_DESCRIBE_TABLE, {"owner": owner, "table_name": table})))


@mcp.tool()
def list_constraints(table_name: str, schema: str = "") -> str:
    """List primary, foreign, unique and check constraints."""
    return run_for_table(schema, table_name, lambda conn, owner, table, q: to_json(
        q.legacy_list_constraints(conn, owner, table) if q is mssql_queries else
        fetch(conn, queries.LEGACY_LIST_CONSTRAINTS, {"owner": owner, "table_name": table})))


@mcp.tool()
def list_indexes(table_name: str, schema: str = "") -> str:
    """List index definitions and indexed columns."""
    return run_for_table(schema, table_name, lambda conn, owner, table, q: to_json(
        q.legacy_list_indexes(conn, owner, table) if q is mssql_queries else
        fetch(conn, queries.LEGACY_LIST_INDEXES, {"owner": owner, "table_name": table})))


@mcp.tool()
def list_relationships(schema: str = "") -> str:
    """List foreign-key relationships within the approved schema."""
    profile, owner = _profile_and_owner(schema)
    with connect(profile) as conn:
        if profile.engine == "sqlserver":
            return to_json(mssql_queries.legacy_list_relationships(conn, owner))
        return to_json(fetch(conn, queries.LEGACY_LIST_RELATIONSHIPS, {"owner": owner}))


@mcp.tool()
def get_comments(table_name: str, schema: str = "") -> str:
    """Table and column comments (Oracle COMMENT ON / SQL Server MS_Description); null means none recorded."""
    def fn(conn, owner, table, q):
        tab, cols = q.comments(conn, owner, table)
        return to_json({
            "table_name": table,
            "table_comment": tab.get(table),
            "columns": [{"column_name": c["column_name"], "comments": c["comments"]} for c in cols],
        })
    return run_for_table(schema, table_name, fn)


@mcp.tool()
def get_column_defaults(table_name: str, schema: str = "") -> str:
    """Column default (or computed) expressions plus virtual/hidden/identity flags."""
    def fn(conn, owner, table, q):
        rows, identity_error = q.columns(conn, owner, table)
        return to_json({
            "table_name": table,
            "identity_info": "unavailable" if identity_error else "available",
            "columns": [{k: r[k] for k in (
                "column_id", "column_name", "data_default", "virtual_column", "hidden_column",
                "identity_column", "default_on_null")} for r in rows],
        })
    return run_for_table(schema, table_name, fn)


@mcp.tool()
def get_check_constraints(table_name: str, schema: str = "") -> str:
    """CHECK constraint conditions; is_not_null marks Oracle's plain NOT NULL checks."""
    return run_for_table(schema, table_name, lambda conn, owner, table, q: to_json(
        q.check_constraints(conn, owner, table)))


@mcp.tool()
def get_index_expressions(table_name: str, schema: str = "") -> str:
    """Function-based index expressions with index type and uniqueness (always empty on SQL Server)."""
    return run_for_table(schema, table_name, lambda conn, owner, table, q: to_json(
        q.index_expressions(conn, owner, table)))


if __name__ == "__main__":
    mcp.run(transport="stdio")

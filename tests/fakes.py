"""Offline stand-ins for a database connection: SQL constants map to canned dictionary rows.

Oracle statements are keyed by their name in queries.py, SQL Server ones as MSSQL_<name>."""
from oradoc import mssql_queries, queries


class FakeConn:
    def __init__(self, data):
        self.data = data  # {statement name: [row dicts]} ; rows may carry table_name for filtering
        self.calls = []


def make_fetch(conn_holder):
    names = {sql: name for name, sql in queries.ALL_STATEMENTS.items()}
    names.update({sql: f"MSSQL_{name}" for name, sql in mssql_queries.ALL_STATEMENTS.items()})

    def fetch(conn, sql, params=None):
        name = names[sql]  # unknown SQL text -> KeyError: only fixed statements are allowed
        params = params or {}
        conn.calls.append((name, dict(params)))
        value = conn.data.get(name, [])
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(params)
        rows = [dict(r) for r in value]
        table = params.get("table_name")
        if table is not None:
            rows = [r for r in rows if r.get("table_name", table) == table]
        return rows

    return fetch

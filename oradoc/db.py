"""Read-only Oracle and SQL Server connections. The password comes only from Windows Credential Manager."""
from contextlib import contextmanager

import keyring
import oracledb

# pymssql's default session options plus a lock timeout, so a catalog read never waits on DDL locks.
MSSQL_SESSION = (
    "SET ARITHABORT ON; SET CONCAT_NULL_YIELDS_NULL ON; SET ANSI_NULLS ON; SET ANSI_NULL_DFLT_ON ON; "
    "SET ANSI_PADDING ON; SET ANSI_WARNINGS ON; SET CURSOR_CLOSE_ON_COMMIT ON; SET QUOTED_IDENTIFIER ON; "
    "SET TEXTSIZE 2147483647; SET LOCK_TIMEOUT {ms}"
)


def get_password(profile):
    password = keyring.get_password(profile.keyring_service, profile.username)
    if not password:
        raise RuntimeError(
            f"Password for profile {profile.name!r} not found in Windows Credential Manager. "
            f"Store it with: python -m oradoc auth --profile {profile.name}"
        )
    return password


@contextmanager
def connect(profile, password=None):
    """Open a connection whose transaction is READ ONLY; always rolled back and closed.

    password is only passed by the local app's connection test, before it is saved.
    SQL Server has no read-only transaction: the session runs inside an implicit transaction that is
    always rolled back, only fixed catalog SELECTs are sent, and the login should hold no more than
    VIEW DEFINITION (the local app warns when it can write)."""
    if profile.engine == "sqlserver":
        conn = _connect_mssql(profile, password or get_password(profile))
    else:
        conn = oracledb.connect(user=profile.username, password=password or get_password(profile), dsn=profile.dsn)
    try:
        if profile.engine != "sqlserver":
            conn.call_timeout = profile.call_timeout_ms
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def _connect_mssql(profile, password):
    import pymssql  # only needed for SQL Server profiles

    hostport, database = profile.dsn.rsplit("/", 1)
    host, port = hostport.rsplit(":", 1)
    seconds = max(1, profile.call_timeout_ms // 1000)
    return pymssql.connect(
        server=host, port=None if "\\" in host else port,  # host\INSTANCE: port comes from SQL Browser
        user=profile.username, password=password, database=database,
        login_timeout=seconds, timeout=seconds, autocommit=False, appname="Atlas",
        encryption="request", conn_properties=MSSQL_SESSION.format(ms=profile.call_timeout_ms),
    )


def fetch(conn, sql, params=None):
    """Run one fixed dictionary query and return rows as dicts with lower-case keys."""
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        columns = [d[0].lower() for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def sanitize_error(exc, profile):
    """Error text safe for logs and documents: connection details are masked."""
    msg = f"{type(exc).__name__}: {exc}"
    for secret in {profile.dsn, profile.dsn.split("/")[0], profile.dsn.split(":")[0], profile.username}:
        if secret:
            msg = msg.replace(secret, "<redacted>")
    return msg

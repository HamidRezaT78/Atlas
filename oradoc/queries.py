"""Fixed, bind-variable SQL against Oracle data dictionary views only.

Every statement here is a SELECT over an ALL_* view (or PRODUCT_COMPONENT_VERSION),
filtered by the :owner bind. Nothing in this module reads application table rows,
and no caller can supply SQL text. tests/test_sql_safety.py enforces this.

Statements with a :table_name bind accept NULL to mean "every table of :owner".
"""
import re

from .config import check_object_name
from .db import fetch

# ---------------------------------------------------------------------------
# Legacy statements: byte-for-byte the SQL of the original MCP tools, so their
# output stays identical.
# ---------------------------------------------------------------------------

LEGACY_LIST_TABLES = """
        SELECT table_name
        FROM all_tables
        WHERE owner = :owner
        ORDER BY table_name
        """

LEGACY_DESCRIBE_TABLE = """
        SELECT column_id, column_name, data_type, data_length,
               data_precision, data_scale, nullable
        FROM all_tab_columns
        WHERE owner = :owner AND table_name = :table_name
        ORDER BY column_id
        """

LEGACY_LIST_CONSTRAINTS = """
        SELECT c.constraint_name, c.constraint_type, c.status,
               cc.column_name, cc.position,
               c.r_owner AS referenced_owner,
               rc.table_name AS referenced_table,
               rcc.column_name AS referenced_column
        FROM all_constraints c
        LEFT JOIN all_cons_columns cc
          ON cc.owner = c.owner
         AND cc.constraint_name = c.constraint_name
         AND cc.table_name = c.table_name
        LEFT JOIN all_constraints rc
          ON rc.owner = c.r_owner
         AND rc.constraint_name = c.r_constraint_name
         AND c.constraint_type = 'R'
        LEFT JOIN all_cons_columns rcc
          ON rcc.owner = rc.owner
         AND rcc.constraint_name = rc.constraint_name
         AND rcc.table_name = rc.table_name
         AND rcc.position = cc.position
        WHERE c.owner = :owner
          AND c.table_name = :table_name
          AND c.constraint_type IN ('P', 'R', 'U', 'C')
        ORDER BY c.constraint_name, cc.position
        """

LEGACY_LIST_INDEXES = """
        SELECT i.index_name, i.uniqueness, ic.column_name,
               ic.column_position, ic.descend
        FROM all_indexes i
        JOIN all_ind_columns ic
          ON ic.index_owner = i.owner
         AND ic.index_name = i.index_name
         AND ic.table_owner = i.table_owner
         AND ic.table_name = i.table_name
        WHERE i.table_owner = :owner
          AND i.table_name = :table_name
        ORDER BY i.index_name, ic.column_position
        """

LEGACY_LIST_RELATIONSHIPS = """
        SELECT c.table_name AS source_table,
               cc.column_name AS source_column,
               rc.table_name AS target_table,
               rcc.column_name AS target_column,
               c.constraint_name
        FROM all_constraints c
        JOIN all_cons_columns cc
          ON cc.owner = c.owner
         AND cc.constraint_name = c.constraint_name
         AND cc.table_name = c.table_name
        JOIN all_constraints rc
          ON rc.owner = c.r_owner
         AND rc.constraint_name = c.r_constraint_name
        JOIN all_cons_columns rcc
          ON rcc.owner = rc.owner
         AND rcc.constraint_name = rc.constraint_name
         AND rcc.table_name = rc.table_name
         AND rcc.position = cc.position
        WHERE c.owner = :owner
          AND c.constraint_type = 'R'
        ORDER BY c.table_name, c.constraint_name, cc.position
        """

TABLE_EXISTS = """
        SELECT COUNT(*) AS n
        FROM all_tables
        WHERE owner = :owner
          AND table_name = :table_name
        """

# ---------------------------------------------------------------------------
# Supplementary metadata (new tools and the documentation engine)
# ---------------------------------------------------------------------------

TABLES = """
        SELECT table_name, temporary, partitioned, iot_type, nested
        FROM all_tables
        WHERE owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
        ORDER BY table_name
        """

# ALL_TAB_COLS also returns hidden/virtual columns (e.g. SYS_NC… of function-based
# indexes). DATA_DEFAULT is a LONG and is fetched as text.
COLUMNS = """
        SELECT table_name, column_id, internal_column_id, column_name, data_type,
               data_length, data_precision, data_scale, nullable,
               char_length, char_used, data_default,
               hidden_column, virtual_column, user_generated
        FROM all_tab_cols
        WHERE owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
          AND table_name IN (SELECT t.table_name FROM all_tables t WHERE t.owner = :owner)
        ORDER BY table_name, internal_column_id
        """

# Oracle 12c+ only; a failure (ORA-00904) is reported as "unavailable", not fatal.
COLUMN_IDENTITY = """
        SELECT table_name, column_name, identity_column, default_on_null
        FROM all_tab_cols
        WHERE owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
          AND table_name IN (SELECT t.table_name FROM all_tables t WHERE t.owner = :owner)
        ORDER BY table_name, internal_column_id
        """

TABLE_COMMENTS = """
        SELECT table_name, comments
        FROM all_tab_comments
        WHERE owner = :owner
          AND table_type = 'TABLE'
          AND (:table_name IS NULL OR table_name = :table_name)
        ORDER BY table_name
        """

COLUMN_COMMENTS = """
        SELECT table_name, column_name, comments
        FROM all_col_comments
        WHERE owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
          AND table_name IN (SELECT t.table_name FROM all_tables t WHERE t.owner = :owner)
        ORDER BY table_name, column_name
        """

CONSTRAINTS = """
        SELECT table_name, constraint_name, constraint_type, status, validated,
               generated, deferrable, deferred, delete_rule, index_name,
               r_owner, r_constraint_name
        FROM all_constraints
        WHERE owner = :owner
          AND constraint_type IN ('P', 'U', 'R', 'C')
          AND (:table_name IS NULL OR table_name = :table_name)
          AND table_name IN (SELECT t.table_name FROM all_tables t WHERE t.owner = :owner)
        ORDER BY table_name, constraint_name
        """

CONSTRAINT_COLUMNS = """
        SELECT table_name, constraint_name, column_name, position
        FROM all_cons_columns
        WHERE owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
        ORDER BY table_name, constraint_name, position, column_name
        """

# SEARCH_CONDITION is a LONG; it is fetched as text.
CHECK_CONDITIONS = """
        SELECT table_name, constraint_name, search_condition, generated,
               status, validated
        FROM all_constraints
        WHERE owner = :owner
          AND constraint_type = 'C'
          AND (:table_name IS NULL OR table_name = :table_name)
          AND table_name IN (SELECT t.table_name FROM all_tables t WHERE t.owner = :owner)
        ORDER BY table_name, constraint_name
        """

INDEXES = """
        SELECT table_name, owner AS index_owner, index_name, index_type, uniqueness,
               status, visibility, partitioned
        FROM all_indexes
        WHERE table_owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
        ORDER BY table_name, index_name
        """

INDEX_COLUMNS = """
        SELECT table_name, index_owner, index_name, column_name,
               column_position, descend
        FROM all_ind_columns
        WHERE table_owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
        ORDER BY table_name, index_name, column_position
        """

# COLUMN_EXPRESSION is a LONG; it is fetched as text.
INDEX_EXPRESSIONS = """
        SELECT table_name, index_owner, index_name, column_position,
               column_expression
        FROM all_ind_expressions
        WHERE table_owner = :owner
          AND (:table_name IS NULL OR table_name = :table_name)
        ORDER BY table_name, index_name, column_position
        """

COUNT_TABLES = """
        SELECT COUNT(*) AS n
        FROM all_tables
        WHERE owner = :owner
        """

COUNT_COLUMNS = """
        SELECT COUNT(*) AS n
        FROM all_tab_columns
        WHERE owner = :owner
          AND table_name IN (SELECT t.table_name FROM all_tables t WHERE t.owner = :owner)
        """

DB_VERSION = """
        SELECT product, version
        FROM product_component_version
        ORDER BY product
        """

LIST_OWNERS = """
        SELECT owner, COUNT(*) AS n
        FROM all_tables
        GROUP BY owner
        ORDER BY owner
        """

ALLOWED_VIEWS = {
    "all_tables", "all_tab_cols", "all_tab_columns", "all_tab_comments",
    "all_col_comments", "all_constraints", "all_cons_columns", "all_indexes",
    "all_ind_columns", "all_ind_expressions", "product_component_version",
}

ALL_STATEMENTS = {
    name: value for name, value in dict(globals()).items()
    if name.isupper() and isinstance(value, str) and "SELECT" in value
}

NOT_NULL_RE = re.compile(r'^\s*"?([A-Za-z0-9_$#]+)"?\s+IS\s+NOT\s+NULL\s*$', re.IGNORECASE)


def clean_text(value):
    """LONG/text values from the dictionary, with trailing whitespace removed."""
    if value is None:
        return None
    return str(value).rstrip() or None


def table_exists(conn, owner, table_name):
    table_name = check_object_name(table_name)
    rows = fetch(conn, TABLE_EXISTS, {"owner": owner, "table_name": table_name})
    if rows[0]["n"] != 1:
        raise ValueError("Table is not in the permitted schema.")
    return table_name


def comments(conn, owner, table_name=None):
    """Table comment plus every column comment (NULL where none is recorded)."""
    params = {"owner": owner, "table_name": table_name}
    tab = {r["table_name"]: clean_text(r["comments"]) for r in fetch(conn, TABLE_COMMENTS, params)}
    cols = [dict(r, comments=clean_text(r["comments"])) for r in fetch(conn, COLUMN_COMMENTS, params)]
    return tab, cols


def columns(conn, owner, table_name=None):
    params = {"owner": owner, "table_name": table_name}
    rows = [dict(r, data_default=clean_text(r["data_default"])) for r in fetch(conn, COLUMNS, params)]
    identity, identity_error = {}, None
    try:
        for r in fetch(conn, COLUMN_IDENTITY, params):
            identity[(r["table_name"], r["column_name"])] = r
    except Exception as exc:  # pre-12c dictionary: columns do not exist
        identity_error = exc
    for r in rows:
        extra = identity.get((r["table_name"], r["column_name"]))
        r["identity_column"] = extra["identity_column"] if extra else None
        r["default_on_null"] = extra["default_on_null"] if extra else None
    return rows, identity_error


def check_constraints(conn, owner, table_name=None):
    params = {"owner": owner, "table_name": table_name}
    cols = {}
    for r in fetch(conn, CONSTRAINT_COLUMNS, params):
        cols.setdefault((r["table_name"], r["constraint_name"]), []).append(r["column_name"])
    out = []
    for r in fetch(conn, CHECK_CONDITIONS, params):
        cond = clean_text(r["search_condition"])
        m = NOT_NULL_RE.match(cond or "")
        out.append({
            "table_name": r["table_name"],
            "constraint_name": r["constraint_name"],
            "columns": cols.get((r["table_name"], r["constraint_name"]), []),
            "search_condition": cond,
            "is_not_null": bool(m),
            "generated": r["generated"],
            "status": r["status"],
            "validated": r["validated"],
        })
    return out


def index_expressions(conn, owner, table_name=None):
    """Function-based index definitions: one row per index column position."""
    params = {"owner": owner, "table_name": table_name}
    exprs = {(r["index_owner"], r["index_name"], r["column_position"]): clean_text(r["column_expression"])
             for r in fetch(conn, INDEX_EXPRESSIONS, params)}
    out = []
    indexes = {(r["index_owner"], r["index_name"]): r for r in fetch(conn, INDEXES, params)}
    for r in fetch(conn, INDEX_COLUMNS, params):
        idx = indexes.get((r["index_owner"], r["index_name"]))
        if not idx or not (idx["index_type"] or "").startswith("FUNCTION-BASED"):
            continue
        out.append({
            "table_name": r["table_name"],
            "index_name": r["index_name"],
            "index_type": idx["index_type"],
            "uniqueness": idx["uniqueness"],
            "column_position": r["column_position"],
            "column_name": r["column_name"],
            "column_expression": exprs.get((r["index_owner"], r["index_name"], r["column_position"])),
        })
    return out

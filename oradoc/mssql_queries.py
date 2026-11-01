"""Fixed, bind-variable SQL against SQL Server catalog views only (the SQL Server twin of queries.py).

Every statement is a SELECT over sys.* catalog views, filtered by the %(owner)s (schema) bind, and
returns the same column names and codes as the Oracle statements (constraint_type P/U/R/C,
status ENABLED/DISABLED, validated VALIDATED/NOT VALIDATED, ...), so collector.build_snapshot,
analysis and rendering are shared. Nothing here reads application table rows and no caller can
supply SQL text; tests/test_sql_safety.py enforces this for both engines.

Statements with a %(table_name)s bind accept NULL to mean "every table of %(owner)s".
Data types are reported in lower case (as SQL Server spells them); analysis.type_label relies on it.
"""
from .config import check_object_name
from .db import fetch

_TABLE_FILTER = """
          AND t.is_ms_shipped = 0
          AND s.name = %(owner)s
          AND (%(table_name)s IS NULL OR t.name = %(table_name)s)"""

TABLE_EXISTS = """
        SELECT t.name AS table_name
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE t.is_ms_shipped = 0
          AND s.name = %(owner)s
          AND t.name = %(table_name)s
        """

TABLES = """
        SELECT t.name AS table_name,
               'N' AS temporary,
               CASE WHEN EXISTS (SELECT 1 FROM sys.partitions p
                                 WHERE p.object_id = t.object_id AND p.index_id IN (0, 1)
                                   AND p.partition_number > 1) THEN 'YES' ELSE 'NO' END AS partitioned,
               CAST(NULL AS varchar(1)) AS iot_type,
               'NO' AS nested
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY t.name
        """

# Lengths: char_length is in characters (nvarchar max_length is in bytes); -1 means MAX.
# Hidden columns (temporal period columns declared HIDDEN) via COLUMNPROPERTY, which is NULL before 2016.
COLUMNS = """
        SELECT t.name AS table_name, c.column_id, c.column_id AS internal_column_id,
               c.name AS column_name, TYPE_NAME(c.user_type_id) AS data_type,
               c.max_length AS data_length,
               CASE WHEN TYPE_NAME(c.system_type_id) IN ('decimal', 'numeric') THEN c.precision END AS data_precision,
               CASE WHEN TYPE_NAME(c.system_type_id) IN ('decimal', 'numeric', 'datetime2', 'time', 'datetimeoffset')
                    THEN c.scale END AS data_scale,
               CASE WHEN c.is_nullable = 1 THEN 'Y' ELSE 'N' END AS nullable,
               CASE WHEN c.max_length = -1 THEN -1
                    WHEN TYPE_NAME(c.system_type_id) IN ('nchar', 'nvarchar') THEN c.max_length / 2
                    WHEN TYPE_NAME(c.system_type_id) IN ('char', 'varchar', 'binary', 'varbinary') THEN c.max_length
               END AS char_length,
               CAST(NULL AS varchar(1)) AS char_used,
               COALESCE(cc.definition, dc.definition) AS data_default,
               CASE WHEN COLUMNPROPERTY(c.object_id, c.name, 'IsHidden') = 1 THEN 'YES' ELSE 'NO' END AS hidden_column,
               CASE WHEN c.is_computed = 1 THEN 'YES' ELSE 'NO' END AS virtual_column,
               'YES' AS user_generated,
               CASE WHEN c.is_identity = 1 THEN 'YES' ELSE 'NO' END AS identity_column,
               CAST(NULL AS varchar(3)) AS default_on_null
        FROM sys.columns c
        JOIN sys.tables t ON t.object_id = c.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        LEFT JOIN sys.default_constraints dc ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        LEFT JOIN sys.computed_columns cc ON cc.object_id = c.object_id AND cc.column_id = c.column_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY t.name, c.column_id
        """

TABLE_COMMENTS = """
        SELECT t.name AS table_name, CAST(ep.value AS nvarchar(4000)) AS comments
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        LEFT JOIN sys.extended_properties ep
          ON ep.class = 1 AND ep.major_id = t.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY t.name
        """

COLUMN_COMMENTS = """
        SELECT t.name AS table_name, c.name AS column_name, CAST(ep.value AS nvarchar(4000)) AS comments
        FROM sys.columns c
        JOIN sys.tables t ON t.object_id = c.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        LEFT JOIN sys.extended_properties ep
          ON ep.class = 1 AND ep.major_id = c.object_id AND ep.minor_id = c.column_id AND ep.name = 'MS_Description'
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY t.name, c.name
        """

# r_constraint_name is the referenced PK/UQ constraint; NULL when the FK references a unique index
# that has no constraint. r_table_name names the referenced table directly in every case.
CONSTRAINTS = """
        SELECT t.name AS table_name, kc.name AS constraint_name,
               CASE kc.type WHEN 'PK' THEN 'P' ELSE 'U' END AS constraint_type,
               CASE WHEN i.is_disabled = 1 THEN 'DISABLED' ELSE 'ENABLED' END AS status,
               'VALIDATED' AS validated,
               CASE WHEN kc.is_system_named = 1 THEN 'GENERATED NAME' ELSE 'USER NAME' END AS generated,
               'NOT DEFERRABLE' AS deferrable, 'IMMEDIATE' AS deferred,
               CAST(NULL AS nvarchar(60)) AS delete_rule, i.name AS index_name,
               CAST(NULL AS sysname) AS r_owner, CAST(NULL AS sysname) AS r_constraint_name,
               CAST(NULL AS sysname) AS r_table_name
        FROM sys.key_constraints kc
        JOIN sys.tables t ON t.object_id = kc.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        LEFT JOIN sys.indexes i ON i.object_id = kc.parent_object_id AND i.index_id = kc.unique_index_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        UNION ALL
        SELECT t.name, fk.name, 'R',
               CASE WHEN fk.is_disabled = 1 THEN 'DISABLED' ELSE 'ENABLED' END,
               CASE WHEN fk.is_not_trusted = 1 THEN 'NOT VALIDATED' ELSE 'VALIDATED' END,
               CASE WHEN fk.is_system_named = 1 THEN 'GENERATED NAME' ELSE 'USER NAME' END,
               'NOT DEFERRABLE', 'IMMEDIATE',
               REPLACE(fk.delete_referential_action_desc, '_', ' '), NULL,
               rs.name, rkc.name, rt.name
        FROM sys.foreign_keys fk
        JOIN sys.tables t ON t.object_id = fk.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.tables rt ON rt.object_id = fk.referenced_object_id
        JOIN sys.schemas rs ON rs.schema_id = rt.schema_id
        LEFT JOIN sys.key_constraints rkc
          ON rkc.parent_object_id = fk.referenced_object_id AND rkc.unique_index_id = fk.key_index_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        UNION ALL
        SELECT t.name, ck.name, 'C',
               CASE WHEN ck.is_disabled = 1 THEN 'DISABLED' ELSE 'ENABLED' END,
               CASE WHEN ck.is_not_trusted = 1 THEN 'NOT VALIDATED' ELSE 'VALIDATED' END,
               CASE WHEN ck.is_system_named = 1 THEN 'GENERATED NAME' ELSE 'USER NAME' END,
               'NOT DEFERRABLE', 'IMMEDIATE', NULL, NULL, NULL, NULL, NULL
        FROM sys.check_constraints ck
        JOIN sys.tables t ON t.object_id = ck.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY 1, 2
        """

CONSTRAINT_COLUMNS = """
        SELECT t.name AS table_name, kc.name AS constraint_name, c.name AS column_name,
               ic.key_ordinal AS position
        FROM sys.key_constraints kc
        JOIN sys.tables t ON t.object_id = kc.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.index_columns ic
          ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id AND ic.key_ordinal > 0
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        UNION ALL
        SELECT t.name, fk.name, c.name, fkc.constraint_column_id
        FROM sys.foreign_keys fk
        JOIN sys.tables t ON t.object_id = fk.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.columns c ON c.object_id = fkc.parent_object_id AND c.column_id = fkc.parent_column_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        UNION ALL
        SELECT t.name, ck.name, c.name, 1
        FROM sys.check_constraints ck
        JOIN sys.tables t ON t.object_id = ck.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.columns c ON c.object_id = ck.parent_object_id AND c.column_id = ck.parent_column_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY 1, 2, 4
        """

FK_REFERENCED_COLUMNS = """
        SELECT t.name AS table_name, fk.name AS constraint_name, rc.name AS column_name,
               fkc.constraint_column_id AS position
        FROM sys.foreign_keys fk
        JOIN sys.tables t ON t.object_id = fk.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY 1, 2, 4
        """

CHECK_CONDITIONS = """
        SELECT t.name AS table_name, ck.name AS constraint_name, ck.definition AS search_condition,
               CASE WHEN ck.is_system_named = 1 THEN 'GENERATED NAME' ELSE 'USER NAME' END AS generated,
               CASE WHEN ck.is_disabled = 1 THEN 'DISABLED' ELSE 'ENABLED' END AS status,
               CASE WHEN ck.is_not_trusted = 1 THEN 'NOT VALIDATED' ELSE 'VALIDATED' END AS validated
        FROM sys.check_constraints ck
        JOIN sys.tables t ON t.object_id = ck.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE 1 = 1""" + _TABLE_FILTER + """
        ORDER BY t.name, ck.name
        """

INDEXES = """
        SELECT t.name AS table_name, s.name AS index_owner, i.name AS index_name,
               i.type_desc AS index_type,
               CASE WHEN i.is_unique = 1 THEN 'UNIQUE' ELSE 'NONUNIQUE' END AS uniqueness,
               CASE WHEN i.is_disabled = 1 THEN 'DISABLED' ELSE 'VALID' END AS status,
               'VISIBLE' AS visibility,
               CASE WHEN ds.type = 'PS' THEN 'YES' ELSE 'NO' END AS partitioned,
               i.filter_definition
        FROM sys.indexes i
        JOIN sys.tables t ON t.object_id = i.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        LEFT JOIN sys.data_spaces ds ON ds.data_space_id = i.data_space_id
        WHERE i.index_id > 0
          AND i.is_hypothetical = 0""" + _TABLE_FILTER + """
        ORDER BY t.name, i.name
        """

INDEX_COLUMNS = """
        SELECT t.name AS table_name, s.name AS index_owner, i.name AS index_name, c.name AS column_name,
               ic.key_ordinal AS column_position,
               CASE WHEN ic.is_descending_key = 1 THEN 'DESC' ELSE 'ASC' END AS descend
        FROM sys.index_columns ic
        JOIN sys.indexes i ON i.object_id = ic.object_id AND i.index_id = ic.index_id
        JOIN sys.tables t ON t.object_id = i.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE ic.key_ordinal > 0
          AND i.is_hypothetical = 0""" + _TABLE_FILTER + """
        ORDER BY t.name, i.name, ic.key_ordinal
        """

# Non-key (INCLUDE) columns: part of what makes two indexes on the same keys different.
INDEX_INCLUDED_COLUMNS = """
        SELECT t.name AS table_name, i.name AS index_name, c.name AS column_name, ic.index_column_id
        FROM sys.index_columns ic
        JOIN sys.indexes i ON i.object_id = ic.object_id AND i.index_id = ic.index_id
        JOIN sys.tables t ON t.object_id = i.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE ic.is_included_column = 1
          AND i.is_hypothetical = 0""" + _TABLE_FILTER + """
        ORDER BY t.name, i.name, ic.index_column_id
        """

COUNT_TABLES = """
        SELECT COUNT(*) AS n
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE t.is_ms_shipped = 0
          AND s.name = %(owner)s
        """

COUNT_COLUMNS = """
        SELECT COUNT(*) AS n
        FROM sys.columns c
        JOIN sys.tables t ON t.object_id = c.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE t.is_ms_shipped = 0
          AND s.name = %(owner)s
          AND ISNULL(COLUMNPROPERTY(c.object_id, c.name, 'IsHidden'), 0) = 0
        """

DB_VERSION = """
        SELECT 'Microsoft SQL Server' AS product,
               CONCAT('Microsoft SQL Server ', CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)),
                      ' (', CAST(SERVERPROPERTY('Edition') AS nvarchar(128)), ')') AS version
        """

LIST_OWNERS = """
        SELECT s.name AS owner, COUNT(*) AS n
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE t.is_ms_shipped = 0
        GROUP BY s.name
        ORDER BY s.name
        """

LIST_DATABASES = """
        SELECT name
        FROM sys.databases
        WHERE database_id > 4
          AND state = 0
          AND HAS_DBACCESS(name) = 1
        ORDER BY name
        """

# Connection test only: warns when the login could change data or structure.
PERMISSIONS = """
        SELECT IS_SRVROLEMEMBER('sysadmin') AS sysadmin,
               IS_ROLEMEMBER('db_owner') AS db_owner,
               IS_ROLEMEMBER('db_datawriter') AS db_datawriter,
               IS_ROLEMEMBER('db_ddladmin') AS db_ddladmin
        """

ALLOWED_VIEWS = {
    "sys.tables", "sys.schemas", "sys.columns", "sys.default_constraints", "sys.computed_columns",
    "sys.extended_properties", "sys.key_constraints", "sys.foreign_keys", "sys.foreign_key_columns",
    "sys.check_constraints", "sys.indexes", "sys.index_columns", "sys.data_spaces", "sys.partitions",
    "sys.databases",
}

ALL_STATEMENTS = {
    name: value for name, value in dict(globals()).items()
    if name.isupper() and not name.startswith("_") and isinstance(value, str) and "SELECT" in value
}

UNBOUND = {"DB_VERSION", "LIST_OWNERS", "LIST_DATABASES", "PERMISSIONS"}  # no schema chosen yet


def clean_text(value):
    if value is None:
        return None
    return str(value).rstrip() or None


def unwrap(expr):
    """Strip the parentheses SQL Server wraps around stored definitions: ((0)) -> 0, ([a]+[b]) -> [a]+[b]."""
    expr = clean_text(expr)
    while expr and expr[0] == "(" and expr[-1] == ")":
        depth = 0
        for i, ch in enumerate(expr):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and i < len(expr) - 1:
                return expr  # the first "(" closes early: not one enclosing pair
        expr = expr[1:-1].strip()
    return expr or None


def table_exists(conn, owner, table_name):
    table_name = check_object_name(table_name, "sqlserver")
    rows = fetch(conn, TABLE_EXISTS, {"owner": owner, "table_name": table_name})
    if len(rows) != 1:
        raise ValueError("Table is not in the permitted schema.")
    return rows[0]["table_name"]


def comments(conn, owner, table_name=None):
    params = {"owner": owner, "table_name": table_name}
    tab = {r["table_name"]: clean_text(r["comments"]) for r in fetch(conn, TABLE_COMMENTS, params)}
    cols = [dict(r, comments=clean_text(r["comments"])) for r in fetch(conn, COLUMN_COMMENTS, params)]
    return tab, cols


def columns(conn, owner, table_name=None):
    """Same shape as queries.columns: (rows, identity_error); identity is always available here."""
    params = {"owner": owner, "table_name": table_name}
    return [dict(r, data_default=unwrap(r["data_default"])) for r in fetch(conn, COLUMNS, params)], None


def constraints(conn, owner, table_name=None):
    """CONSTRAINTS rows with r_columns (the referenced columns, in FK column order) on FK rows."""
    params = {"owner": owner, "table_name": table_name}
    refs = {}
    for r in fetch(conn, FK_REFERENCED_COLUMNS, params):
        refs.setdefault((r["table_name"], r["constraint_name"]), []).append((r["position"], r["column_name"]))
    rows = fetch(conn, CONSTRAINTS, params)
    for r in rows:
        if r["constraint_type"] == "R":
            r["r_columns"] = [c for _, c in sorted(refs.get((r["table_name"], r["constraint_name"]), []))]
    return rows


def indexes(conn, owner, table_name=None):
    """INDEXES rows plus included_columns and the unwrapped filter_definition."""
    params = {"owner": owner, "table_name": table_name}
    inc = {}
    for r in fetch(conn, INDEX_INCLUDED_COLUMNS, params):
        inc.setdefault((r["table_name"], r["index_name"]), []).append(r["column_name"])
    return [dict(r, filter_definition=unwrap(r["filter_definition"]),
                 included_columns=inc.get((r["table_name"], r["index_name"]), []))
            for r in fetch(conn, INDEXES, params)]


def check_constraints(conn, owner, table_name=None):
    params = {"owner": owner, "table_name": table_name}
    cols = {}
    for r in fetch(conn, CONSTRAINT_COLUMNS, params):
        cols.setdefault((r["table_name"], r["constraint_name"]), []).append(r["column_name"])
    return [{
        "table_name": r["table_name"],
        "constraint_name": r["constraint_name"],
        "columns": cols.get((r["table_name"], r["constraint_name"]), []),
        "search_condition": unwrap(r["search_condition"]),
        "is_not_null": False,  # SQL Server keeps NOT NULL on the column, never as a CHECK
        "generated": r["generated"],
        "status": r["status"],
        "validated": r["validated"],
    } for r in fetch(conn, CHECK_CONDITIONS, params)]


def index_expressions(conn, owner, table_name=None):
    """SQL Server has no function-based indexes (expressions are indexed through computed columns)."""
    return []


# ---------------------------------------------------------------------------
# Shapes of the original MCP tools (Oracle: queries.LEGACY_*), built from the statements above.
# ---------------------------------------------------------------------------

def legacy_list_tables(conn, owner):
    return [{"table_name": r["table_name"]}
            for r in fetch(conn, TABLES, {"owner": owner, "table_name": None})]


def legacy_describe_table(conn, owner, table_name):
    rows, _ = columns(conn, owner, table_name)
    return [{
        "column_id": r["column_id"], "column_name": r["column_name"], "data_type": r["data_type"],
        "data_length": r["char_length"] if r["char_length"] is not None else r["data_length"],
        "data_precision": r["data_precision"], "data_scale": r["data_scale"], "nullable": r["nullable"],
    } for r in rows]


def legacy_list_constraints(conn, owner, table_name):
    params = {"owner": owner, "table_name": table_name}
    cols = {}
    for r in fetch(conn, CONSTRAINT_COLUMNS, params):
        cols.setdefault(r["constraint_name"], []).append((r["position"], r["column_name"]))
    out = []
    for c in constraints(conn, owner, table_name):
        members = [n for _, n in sorted(cols.get(c["constraint_name"], []))] or [None]
        refs = c.get("r_columns") or []
        for pos, name in enumerate(members, start=1):
            out.append({
                "constraint_name": c["constraint_name"], "constraint_type": c["constraint_type"],
                "status": c["status"], "column_name": name, "position": pos if name else None,
                "referenced_owner": c["r_owner"], "referenced_table": c["r_table_name"],
                "referenced_column": refs[pos - 1] if pos <= len(refs) else None,
            })
    return out


def legacy_list_indexes(conn, owner, table_name):
    params = {"owner": owner, "table_name": table_name}
    uniq = {r["index_name"]: r["uniqueness"] for r in fetch(conn, INDEXES, params)}
    return [{
        "index_name": r["index_name"], "uniqueness": uniq.get(r["index_name"]),
        "column_name": r["column_name"], "column_position": r["column_position"], "descend": r["descend"],
    } for r in fetch(conn, INDEX_COLUMNS, params)]


def legacy_list_relationships(conn, owner):
    params = {"owner": owner, "table_name": None}
    src = {}
    for r in fetch(conn, CONSTRAINT_COLUMNS, params):
        src.setdefault((r["table_name"], r["constraint_name"]), []).append((r["position"], r["column_name"]))
    out = []
    for c in constraints(conn, owner):
        if c["constraint_type"] != "R":
            continue
        cols = [n for _, n in sorted(src.get((c["table_name"], c["constraint_name"]), []))]
        for sc, tc in zip(cols, c["r_columns"]):
            out.append({"source_table": c["table_name"], "source_column": sc, "target_table": c["r_table_name"],
                        "target_column": tc, "constraint_name": c["constraint_name"]})
    return out

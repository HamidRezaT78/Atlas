"""Collect a complete metadata snapshot of one allowlisted schema.

Each dictionary section is fetched independently; a failing section is recorded
(with connection details masked) instead of being silently skipped.
The snapshot holds no connection details and no timestamps, so it is reproducible.
"""
import hashlib
import json

from . import mssql_queries, queries
from .db import connect, fetch, sanitize_error

SNAPSHOT_FORMAT = 1


def _section(sections, name, profile, fn, required=False):
    try:
        result = fn()
        sections[name] = {"status": "ok"}
        return result
    except Exception as exc:
        sections[name] = {"status": "failed", "error": sanitize_error(exc, profile)}
        if required:
            raise RuntimeError(f"Required section {name!r} failed: {sections[name]['error']}") from None
        return None


def collect(profile, schema):
    owner = profile.check_schema(schema)
    try:
        if profile.engine == "sqlserver":
            return _collect_mssql(profile, owner)
        return _collect(profile, owner)
    except RuntimeError:
        raise
    except Exception as exc:  # connection errors: never surface DSN or username
        raise RuntimeError(sanitize_error(exc, profile)) from None


def _collect(profile, owner):
    sections = {}
    with connect(profile) as conn:
        p = {"owner": owner, "table_name": None}
        tables = _section(sections, "tables", profile, lambda: fetch(conn, queries.TABLES, p), required=True)
        cols_and_err = _section(sections, "columns", profile, lambda: queries.columns(conn, owner))
        tab_comments = _section(sections, "table_comments", profile, lambda: fetch(conn, queries.TABLE_COMMENTS, p))
        col_comments = _section(sections, "column_comments", profile, lambda: fetch(conn, queries.COLUMN_COMMENTS, p))
        constraints = _section(sections, "constraints", profile, lambda: fetch(conn, queries.CONSTRAINTS, p))
        cons_cols = _section(sections, "constraint_columns", profile, lambda: fetch(conn, queries.CONSTRAINT_COLUMNS, p))
        checks = _section(sections, "check_conditions", profile, lambda: queries.check_constraints(conn, owner))
        indexes = _section(sections, "indexes", profile, lambda: fetch(conn, queries.INDEXES, p))
        ind_cols = _section(sections, "index_columns", profile, lambda: fetch(conn, queries.INDEX_COLUMNS, p))
        ind_expr = _section(sections, "index_expressions", profile, lambda: fetch(conn, queries.INDEX_EXPRESSIONS, p))
        n_tables = _section(sections, "count_tables", profile, lambda: fetch(conn, queries.COUNT_TABLES, {"owner": owner}))
        n_cols = _section(sections, "count_columns", profile, lambda: fetch(conn, queries.COUNT_COLUMNS, {"owner": owner}))
        version = _section(sections, "db_version", profile, lambda: fetch(conn, queries.DB_VERSION))

    columns, identity_error = cols_and_err if cols_and_err else (None, None)
    if identity_error is not None:
        sections["column_identity"] = {"status": "unavailable", "error": sanitize_error(identity_error, profile)}
    elif columns is not None:
        sections["column_identity"] = {"status": "ok"}

    return build_snapshot(
        owner=owner, profile_name=profile.name, tables=tables, columns=columns,
        tab_comments=tab_comments, col_comments=col_comments, constraints=constraints,
        cons_cols=cons_cols, checks=checks, indexes=indexes, ind_cols=ind_cols, ind_expr=ind_expr,
        counts={"tables": n_tables[0]["n"] if n_tables else None,
                "columns": n_cols[0]["n"] if n_cols else None},
        version=version, sections=sections,
    )


def _collect_mssql(profile, owner):
    q = mssql_queries
    sections = {}
    with connect(profile) as conn:
        p = {"owner": owner, "table_name": None}
        tables = _section(sections, "tables", profile, lambda: fetch(conn, q.TABLES, p), required=True)
        cols_and_err = _section(sections, "columns", profile, lambda: q.columns(conn, owner))
        tab_comments = _section(sections, "table_comments", profile, lambda: fetch(conn, q.TABLE_COMMENTS, p))
        col_comments = _section(sections, "column_comments", profile, lambda: fetch(conn, q.COLUMN_COMMENTS, p))
        constraints = _section(sections, "constraints", profile, lambda: q.constraints(conn, owner))
        cons_cols = _section(sections, "constraint_columns", profile, lambda: fetch(conn, q.CONSTRAINT_COLUMNS, p))
        checks = _section(sections, "check_conditions", profile, lambda: q.check_constraints(conn, owner))
        indexes = _section(sections, "indexes", profile, lambda: q.indexes(conn, owner))
        ind_cols = _section(sections, "index_columns", profile, lambda: fetch(conn, q.INDEX_COLUMNS, p))
        n_tables = _section(sections, "count_tables", profile, lambda: fetch(conn, q.COUNT_TABLES, {"owner": owner}))
        n_cols = _section(sections, "count_columns", profile, lambda: fetch(conn, q.COUNT_COLUMNS, {"owner": owner}))
        version = _section(sections, "db_version", profile, lambda: fetch(conn, q.DB_VERSION))

    columns = cols_and_err[0] if cols_and_err else None
    if columns is not None:
        sections["column_identity"] = {"status": "ok"}
    return build_snapshot(
        owner=owner, profile_name=profile.name, tables=tables, columns=columns,
        tab_comments=tab_comments, col_comments=col_comments, constraints=constraints,
        cons_cols=cons_cols, checks=checks, indexes=indexes, ind_cols=ind_cols, ind_expr=[],
        counts={"tables": n_tables[0]["n"] if n_tables else None,
                "columns": n_cols[0]["n"] if n_cols else None},
        version=version, sections=sections, engine="sqlserver",
    )


def _s(v):
    return None if v is None else str(v)


def build_snapshot(*, owner, profile_name, tables, columns, tab_comments, col_comments, constraints,
                   cons_cols, checks, indexes, ind_cols, ind_expr, counts, version, sections, engine=None):
    """Assemble the snapshot from raw dictionary rows (None = section failed).

    engine is None for Oracle, so Oracle snapshots (and their fingerprints) are unchanged."""
    snap_tables = {}
    for t in sorted(tables, key=lambda r: r["table_name"]):
        snap_tables[t["table_name"]] = {
            "name": t["table_name"],
            "temporary": t.get("temporary"), "partitioned": t.get("partitioned"),
            "iot_type": t.get("iot_type"), "nested": t.get("nested"),
            "comment": None, "columns": [], "hidden_columns": [], "constraints": [], "indexes": [],
        }

    tc = {r["table_name"]: queries.clean_text(r["comments"]) for r in (tab_comments or [])}
    cc = {(r["table_name"], r["column_name"]): queries.clean_text(r["comments"]) for r in (col_comments or [])}
    for name, t in snap_tables.items():
        t["comment"] = tc.get(name)

    for r in sorted(columns or [], key=lambda r: (r["table_name"], r["internal_column_id"] or 0)):
        t = snap_tables.get(r["table_name"])
        if t is None:
            continue
        col = {
            "name": r["column_name"], "column_id": r["column_id"],
            "data_type": r["data_type"], "data_length": r["data_length"],
            "data_precision": r["data_precision"], "data_scale": r["data_scale"],
            "char_length": r.get("char_length"), "char_used": r.get("char_used"),
            "nullable": r["nullable"] == "Y", "default": r["data_default"],
            "virtual": r.get("virtual_column") == "YES", "hidden": r.get("hidden_column") == "YES",
            "user_generated": r.get("user_generated") != "NO",
            "identity": r.get("identity_column") == "YES" if r.get("identity_column") else None,
            "default_on_null": r.get("default_on_null") == "YES" if r.get("default_on_null") else None,
            "comment": cc.get((r["table_name"], r["column_name"])),
        }
        (t["hidden_columns"] if col["hidden"] else t["columns"]).append(col)

    cols_by_cons = {}
    for r in cons_cols or []:
        cols_by_cons.setdefault((r["table_name"], r["constraint_name"]), []).append(
            (r["position"] or 0, r["column_name"]))
    cons_index = {}
    for r in constraints or []:
        cons_index[r["constraint_name"]] = r
    check_by_name = {(c["table_name"], c["constraint_name"]): c for c in checks or []}

    relationships = []
    for r in sorted(constraints or [], key=lambda r: (r["table_name"], r["constraint_name"])):
        t = snap_tables.get(r["table_name"])
        if t is None:
            continue
        cols = [c for _, c in sorted(cols_by_cons.get((r["table_name"], r["constraint_name"]), []))]
        c = {
            "name": r["constraint_name"], "type": r["constraint_type"], "columns": cols,
            "status": r["status"], "validated": r["validated"], "generated": r["generated"],
            "deferrable": r["deferrable"], "deferred": r["deferred"],
            "delete_rule": r["delete_rule"], "index_name": r["index_name"],
        }
        if r["constraint_type"] == "C":
            chk = check_by_name.get((r["table_name"], r["constraint_name"]))
            c["condition"] = chk["search_condition"] if chk else None
            c["is_not_null"] = chk["is_not_null"] if chk else None
        if r["constraint_type"] == "R":
            ref = cons_index.get(r["r_constraint_name"]) if r["r_owner"] == owner else None
            c["ref_owner"] = r["r_owner"]
            c["ref_constraint"] = r["r_constraint_name"]
            c["ref_table"] = ref["table_name"] if ref else None
            c["ref_columns"] = ([cn for _, cn in sorted(cols_by_cons.get((ref["table_name"], ref["constraint_name"]), []))]
                                if ref else [])
            if ref is None and r["r_owner"] == owner and r.get("r_table_name"):
                # SQL Server: the FK references a unique index without a constraint
                c["ref_table"], c["ref_columns"] = r["r_table_name"], list(r.get("r_columns") or [])
            relationships.append({
                "constraint": r["constraint_name"], "source_table": r["table_name"], "source_columns": cols,
                "target_owner": r["r_owner"], "target_table": c["ref_table"], "target_columns": c["ref_columns"],
                "delete_rule": r["delete_rule"], "status": r["status"], "validated": r["validated"],
                "external": r["r_owner"] != owner,
            })
        t["constraints"].append(c)

    # Keyed by table too: SQL Server index names are only unique per table.
    expr = {(r["index_owner"], r["table_name"], r["index_name"], r["column_position"]):
            queries.clean_text(r["column_expression"]) for r in ind_expr or []}
    icols = {}
    for r in ind_cols or []:
        icols.setdefault((r["index_owner"], r["table_name"], r["index_name"]), []).append({
            "name": r["column_name"], "position": r["column_position"], "descend": r["descend"],
            "expression": expr.get((r["index_owner"], r["table_name"], r["index_name"], r["column_position"])),
        })
    for r in sorted(indexes or [], key=lambda r: (r["table_name"], r["index_name"])):
        t = snap_tables.get(r["table_name"])
        if t is None:
            continue
        ix = {
            "name": r["index_name"], "owner": r["index_owner"], "type": r["index_type"],
            "uniqueness": r["uniqueness"], "status": r["status"], "visibility": r.get("visibility"),
            "partitioned": r.get("partitioned"),
            "columns": sorted(icols.get((r["index_owner"], r["table_name"], r["index_name"]), []),
                              key=lambda c: c["position"]),
        }
        if "included_columns" in r:  # SQL Server only, so Oracle snapshots keep their shape
            ix["include"] = r["included_columns"]
            ix["filter"] = r["filter_definition"]
        t["indexes"].append(ix)

    snapshot = {
        "format": SNAPSHOT_FORMAT,
        "schema": owner,
        "profile": profile_name,
        "db_version": [{"product": _s(v["product"]), "version": _s(v["version"])} for v in version] if version else None,
        "counts": counts,
        "sections": dict(sorted(sections.items())),
        "tables": snap_tables,
        "relationships": sorted(relationships, key=lambda r: (r["source_table"], r["constraint"])),
    }
    if engine:
        snapshot["engine"] = engine
    snapshot["fingerprint"] = fingerprint(snapshot)
    return snapshot


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, default=str)


def fingerprint(snapshot):
    body = {k: v for k, v in snapshot.items() if k != "fingerprint"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()[:16]

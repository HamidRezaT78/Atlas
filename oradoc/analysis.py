"""Structural analysis of a snapshot.

Every finding carries a kind:
  verified  - read directly from the data dictionary (or a recorded comment)
  inferred  - an interpretation supported by at least one structural signal
              (constraints, keys, types, check conditions, column-set overlap);
              never derived from a table or column name alone
  question  - something the metadata cannot answer; needs a person
and a list of evidence items naming the dictionary source.
"""
import re

ORACLE_RESERVED = set("""
ACCESS ADD ALL ALTER AND ANY AS ASC AUDIT BETWEEN BY CHAR CHECK CLUSTER COLUMN COMMENT
COMPRESS CONNECT CREATE CURRENT DATE DECIMAL DEFAULT DELETE DESC DISTINCT DROP ELSE
EXCLUSIVE EXISTS FILE FLOAT FOR FROM GRANT GROUP HAVING IDENTIFIED IMMEDIATE IN INCREMENT
INDEX INITIAL INSERT INTEGER INTERSECT INTO IS LEVEL LIKE LOCK LONG MAXEXTENTS MINUS
MLSLABEL MODE MODIFY NOAUDIT NOCOMPRESS NOT NOWAIT NULL NUMBER OF OFFLINE ON ONLINE
OPTION OR ORDER PCTFREE PRIOR PUBLIC RAW RENAME RESOURCE REVOKE ROW ROWID ROWNUM ROWS
SELECT SESSION SET SHARE SIZE SMALLINT START SUCCESSFUL SYNONYM SYSDATE TABLE THEN TO
TRIGGER UID UNION UNIQUE UPDATE USER VALIDATE VALUES VARCHAR VARCHAR2 VIEW WHENEVER
WHERE WITH
""".split())

# T-SQL reserved keywords (Microsoft docs, "Reserved Keywords (Transact-SQL)").
MSSQL_RESERVED = set("""
ADD ALL ALTER AND ANY AS ASC AUTHORIZATION BACKUP BEGIN BETWEEN BREAK BROWSE BULK BY CASCADE CASE
CHECK CHECKPOINT CLOSE CLUSTERED COALESCE COLLATE COLUMN COMMIT COMPUTE CONSTRAINT CONTAINS
CONTAINSTABLE CONTINUE CONVERT CREATE CROSS CURRENT CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP
CURRENT_USER CURSOR DATABASE DBCC DEALLOCATE DECLARE DEFAULT DELETE DENY DESC DISK DISTINCT
DISTRIBUTED DOUBLE DROP DUMP ELSE END ERRLVL ESCAPE EXCEPT EXEC EXECUTE EXISTS EXIT EXTERNAL FETCH
FILE FILLFACTOR FOR FOREIGN FREETEXT FREETEXTTABLE FROM FULL FUNCTION GOTO GRANT GROUP HAVING
HOLDLOCK IDENTITY IDENTITY_INSERT IDENTITYCOL IF IN INDEX INNER INSERT INTERSECT INTO IS JOIN KEY
KILL LEFT LIKE LINENO LOAD MERGE NATIONAL NOCHECK NONCLUSTERED NOT NULL NULLIF OF OFF OFFSETS ON
OPEN OPENDATASOURCE OPENQUERY OPENROWSET OPENXML OPTION OR ORDER OUTER OVER PERCENT PIVOT PLAN
PRECISION PRIMARY PRINT PROC PROCEDURE PUBLIC RAISERROR READ READTEXT RECONFIGURE REFERENCES
REPLICATION RESTORE RESTRICT RETURN REVERT REVOKE RIGHT ROLLBACK ROWCOUNT ROWGUIDCOL RULE SAVE
SCHEMA SECURITYAUDIT SELECT SEMANTICKEYPHRASETABLE SEMANTICSIMILARITYDETAILSTABLE
SEMANTICSIMILARITYTABLE SESSION_USER SET SETUSER SHUTDOWN SOME STATISTICS SYSTEM_USER TABLE
TABLESAMPLE TEXTSIZE THEN TO TOP TRAN TRANSACTION TRIGGER TRUNCATE TRY_CONVERT TSEQUAL UNION
UNIQUE UNPIVOT UPDATE UPDATETEXT USE USER VALUES VARYING VIEW WAITFOR WHEN WHERE WHILE WITH
WITHIN WRITETEXT
""".split())

# Dictionary names quoted in evidence, per engine (Oracle names are the keys and stay as they are).
SOURCE_NAMES = {
    "sqlserver": {
        "ALL_TAB_COMMENTS": "sys.extended_properties (MS_Description)",
        "ALL_CONSTRAINTS": "sys.*_constraints / sys.foreign_keys",
        "ALL_CONSTRAINTS.SEARCH_CONDITION": "sys.check_constraints.definition",
        "ALL_CONSTRAINTS.INDEX_NAME": "sys.key_constraints.unique_index_id",
        "ALL_CONSTRAINTS.R_OWNER": "sys.foreign_keys (referenced schema)",
        "ALL_TAB_COLS": "sys.columns",
        "ALL_INDEXES": "sys.indexes",
        "ALL_IND_COLUMNS": "sys.index_columns",
        "Oracle SQL reserved words": "T-SQL reserved keywords",
    },
}
MSSQL_LENGTH_TYPES = {"char", "varchar", "nchar", "nvarchar", "binary", "varbinary"}
MSSQL_INT_TYPES = {"bit", "tinyint", "smallint", "int", "bigint"}
# SQL Server stores "c IN ('a','b')" as "[c]='a' OR [c]='b'".
OR_TERM_RE = re.compile(r"^\(?\[?([^\]\s=()]+)\]?\s*=\s*\(?(N?'(?:[^']|'')*'|-?\d+(?:\.\d+)?)\)?\)?$")

IN_LIST_RE = re.compile(r'^\s*"?([A-Za-z0-9_$#]+)"?\s+IN\s*\(([^()]*)\)\s*$', re.IGNORECASE)
ID_LIKE_RE = re.compile(r".+_(ID|BY)$")


def type_label(col):
    t = col["data_type"]
    if t.islower():  # SQL Server spells its types in lower case; Oracle in upper case
        return _mssql_type_label(col)
    if t in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "RAW"):
        if col.get("char_used") == "C" and col.get("char_length"):
            return f"{t}({col['char_length']} CHAR)"
        return f"{t}({col['data_length']})"
    if t == "NUMBER":
        p, s = col["data_precision"], col["data_scale"]
        if p is None and s is None:
            return "NUMBER"
        if p is None:
            return f"NUMBER(*,{s})"
        return f"NUMBER({p},{s})" if s is not None else f"NUMBER({p})"
    return t


def _mssql_type_label(col):
    t = col["data_type"]
    if t in MSSQL_LENGTH_TYPES:
        n = col.get("char_length")
        return f"{t}(MAX)" if n == -1 else f"{t}({n})"
    if t in ("decimal", "numeric"):
        return f"{t}({col['data_precision']},{col['data_scale']})"
    if t in ("datetime2", "time", "datetimeoffset") and col.get("data_scale") is not None:
        return f"{t}({col['data_scale']})"
    return t


def parse_allowed_values(condition):
    """(column, [values]) for "C IN (...)" (Oracle) or "[C]=v OR [C]=w ..." (SQL Server), else None."""
    m = IN_LIST_RE.match(condition)
    if m:
        return m.group(1), [v.strip() for v in m.group(2).split(",") if v.strip()]
    terms = [OR_TERM_RE.match(part.strip()) for part in re.split(r"\s+OR\s+", condition, flags=re.IGNORECASE)]
    if len(terms) > 1 and all(terms) and len({x.group(1).casefold() for x in terms}) == 1:
        return terms[0].group(1), [x.group(2) for x in terms]
    return None


def type_key(col):
    return (col["data_type"], col["data_precision"], col["data_scale"], col["data_length"])


def finding(code, kind, *, table=None, column=None, severity="info", params=None, evidence=None):
    return {"code": code, "kind": kind, "severity": severity, "table": table, "column": column,
            "params": params or {}, "evidence": evidence or []}


def ev(source, detail):
    return {"source": source, "detail": detail}


def analyze(snap):
    tables = snap["tables"]
    rels = snap["relationships"]
    out = []
    engine = snap.get("engine", "oracle")
    names = SOURCE_NAMES.get(engine, {})
    reserved = MSSQL_RESERVED if engine == "sqlserver" else ORACLE_RESERVED

    def ev(source, detail):  # evidence quoting this engine's dictionary names
        return {"source": names.get(source, source), "detail": detail}

    out_by = {t: [r for r in rels if r["source_table"] == t] for t in tables}
    in_by = {t: [r for r in rels if r["target_table"] == t and not r["external"]] for t in tables}
    fk_cols = {(r["source_table"], c) for r in rels for c in r["source_columns"]}

    def pk_of(t):
        return next((c for c in tables[t]["constraints"] if c["type"] == "P"), None)

    def col(t, name):
        return next((c for c in tables[t]["columns"] + tables[t]["hidden_columns"] if c["name"] == name), None)

    # ---- per-table verified descriptions ----
    for name, t in tables.items():
        if t["comment"]:
            out.append(finding("tab_comment", "verified", table=name, params={"text": t["comment"]},
                               evidence=[ev("ALL_TAB_COMMENTS", "COMMENTS")]))
        if in_by[name]:
            srcs = sorted({r["source_table"] for r in in_by[name]})
            out.append(finding("tab_referenced_by", "verified", table=name, params={"tables": srcs},
                               evidence=[ev("ALL_CONSTRAINTS", r["constraint"]) for r in in_by[name]]))
        if out_by[name]:
            tgts = sorted({r["target_table"] or f"{r['target_owner']}.?" for r in out_by[name]})
            out.append(finding("tab_references", "verified", table=name, params={"tables": tgts},
                               evidence=[ev("ALL_CONSTRAINTS", r["constraint"]) for r in out_by[name]]))
        for c in t["columns"]:
            if c["identity"]:
                out.append(finding("col_identity", "verified", table=name, column=c["name"],
                                   params={"default": c["default"]},
                                   evidence=[ev("ALL_TAB_COLS", "IDENTITY_COLUMN=YES")]))

    # ---- check-constraint based facts and inferences ----
    for name, t in tables.items():
        for c in t["constraints"]:
            if c["type"] != "C" or c.get("is_not_null") or not c.get("condition"):
                continue
            parsed = parse_allowed_values(c["condition"])
            if not parsed:
                out.append(finding("chk_condition", "verified", table=name, column=(c["columns"] or [None])[0],
                                   params={"constraint": c["name"], "condition": c["condition"]},
                                   evidence=[ev("ALL_CONSTRAINTS.SEARCH_CONDITION", c["name"])]))
                continue
            cname, values = parsed
            if engine == "sqlserver":  # case-insensitive names: use the column's own spelling
                cname = next((x["name"] for x in t["columns"] if x["name"].casefold() == cname.casefold()), cname)
            else:
                cname = cname.upper()
            out.append(finding("chk_allowed_values", "verified", table=name, column=cname,
                               params={"constraint": c["name"], "values": values},
                               evidence=[ev("ALL_CONSTRAINTS.SEARCH_CONDITION", f"{c['name']}: {c['condition']}")]))
            column = col(name, cname)
            numeric = column and column["data_type"] == "NUMBER"
            flag_type = (numeric and column["data_precision"] == 1) or (column and column["data_type"] in MSSQL_INT_TYPES)
            if flag_type and sorted(values) == ["0", "1"]:
                out.append(finding("inf_flag", "inferred", table=name, column=cname,
                                   evidence=[ev("ALL_CONSTRAINTS.SEARCH_CONDITION", c["condition"]),
                                             ev("ALL_TAB_COLS", type_label(column))]))
            elif len(values) > 2:
                out.append(finding("inf_enum", "inferred", table=name, column=cname, params={"values": values},
                                   evidence=[ev("ALL_CONSTRAINTS.SEARCH_CONDITION", c["condition"])]))
                out.append(finding("q_enum_meaning", "question", table=name, column=cname,
                                   params={"values": values},
                                   evidence=[ev("ALL_CONSTRAINTS.SEARCH_CONDITION", c["condition"])]))

    # ---- structural inferences ----
    for name, t in tables.items():
        if in_by[name] and not out_by[name] and pk_of(name) and len(t["columns"]) <= 8:
            out.append(finding("inf_lookup", "inferred", table=name,
                               params={"incoming": len(in_by[name]), "columns": len(t["columns"])},
                               evidence=[ev("ALL_CONSTRAINTS", f"{len(in_by[name])} incoming FK, 0 outgoing FK"),
                                         ev("ALL_TAB_COLS", f"{len(t['columns'])} columns")]))
    for name, t in tables.items():
        if pk_of(name) or len(t["columns"]) < 3:
            continue
        mine = {(c["name"], c["data_type"]) for c in t["columns"]}
        best = None
        for other, o in tables.items():
            if other == name or not pk_of(other):
                continue
            theirs = {(c["name"], c["data_type"]) for c in o["columns"]}
            share = len(mine & theirs) / len(mine)
            if share >= 0.8 and (best is None or share > best[1] or (share == best[1] and other < best[0])):
                best = (other, share, len(mine & theirs))
        if best:
            out.append(finding("inf_copy_of", "inferred", table=name,
                               params={"other": best[0], "pct": round(best[1] * 100), "matched": best[2],
                                       "total": len(mine)},
                               evidence=[ev("ALL_TAB_COLS", f"{best[2]}/{len(mine)} (name, type) pairs shared with {best[0]}"),
                                         ev("ALL_CONSTRAINTS", "no primary key")]))

    pairs = sorted({tuple(sorted((a["source_table"], a["target_table"])))
                    for a in rels for b in rels
                    if a["target_table"] and a["source_table"] == b["target_table"]
                    and a["target_table"] == b["source_table"] and a["source_table"] != a["target_table"]})
    for a, b in pairs:
        links = [r for r in rels if {r["source_table"], r["target_table"]} == {a, b}]
        unique_backed = any(
            any(c["type"] in ("P", "U") and c["columns"] == r["source_columns"] for c in tables[r["source_table"]]["constraints"])
            for r in links)
        out.append(finding("obs_bidirectional", "verified", severity="info", table=a,
                           params={"a": a, "b": b, "constraints": [r["constraint"] for r in links]},
                           evidence=[ev("ALL_CONSTRAINTS", r["constraint"]) for r in links]))
        out.append(finding("inf_match_link", "inferred", table=a,
                           params={"a": a, "b": b, "unique": unique_backed},
                           evidence=[ev("ALL_CONSTRAINTS", ", ".join(r["constraint"] for r in links))]))

    # ---- structural observations (verified) ----
    for name, t in tables.items():
        if not pk_of(name):
            out.append(finding("obs_no_pk", "verified", severity="review", table=name,
                               evidence=[ev("ALL_CONSTRAINTS", "no constraint_type='P'")]))
        if not out_by[name] and not in_by[name]:
            out.append(finding("obs_isolated", "verified", table=name,
                               evidence=[ev("ALL_CONSTRAINTS", "no FK in or out")]))
        for c in t["constraints"]:
            if c["status"] != "ENABLED" or c["validated"] != "VALIDATED":
                out.append(finding("obs_constraint_state", "verified", severity="review", table=name,
                                   params={"constraint": c["name"], "status": c["status"], "validated": c["validated"]},
                                   evidence=[ev("ALL_CONSTRAINTS", "STATUS/VALIDATED")]))
        backing = {c["index_name"] for c in t["constraints"] if c["type"] in ("P", "U") and c["index_name"]}
        seen = {}
        for ix in t["indexes"]:
            cols = tuple((c["expression"] or c["name"]) for c in ix["columns"])
            key = cols
            if "include" in ix:  # SQL Server: same keys but other INCLUDE columns or filter is not a duplicate
                key += (tuple(sorted(ix["include"])), ix["filter"])
            if key in seen:
                out.append(finding("obs_duplicate_index", "verified", severity="review", table=name,
                                   params={"index": ix["name"], "other": seen[key], "columns": list(cols)},
                                   evidence=[ev("ALL_IND_COLUMNS", ", ".join(cols))]))
            else:
                seen[key] = ix["name"]
            if ix["uniqueness"] == "UNIQUE" and ix["name"] not in backing:
                out.append(finding("obs_unique_index_no_constraint", "verified", table=name,
                                   params={"index": ix["name"], "columns": [c["expression"] or c["name"] for c in ix["columns"]]},
                                   evidence=[ev("ALL_INDEXES", "UNIQUENESS=UNIQUE"),
                                             ev("ALL_CONSTRAINTS.INDEX_NAME", "no PK/UK uses this index")]))
            if ix["status"] not in ("VALID", "N/A") or (ix.get("visibility") or "VISIBLE") != "VISIBLE":
                out.append(finding("obs_index_state", "verified", severity="review", table=name,
                                   params={"index": ix["name"], "status": ix["status"], "visibility": ix.get("visibility")},
                                   evidence=[ev("ALL_INDEXES", "STATUS/VISIBILITY")]))
        for c in t["columns"]:
            if c["name"].upper() in reserved:
                out.append(finding("obs_reserved_word", "verified", table=name, column=c["name"],
                                   evidence=[ev("Oracle SQL reserved words", c["name"])]))
            if ID_LIKE_RE.match(c["name"]) and (name, c["name"]) not in fk_cols:
                pk = pk_of(name)
                if not (pk and c["name"] in pk["columns"]):
                    out.append(finding("q_id_like_no_fk", "question", table=name, column=c["name"],
                                       params={"type": type_label(c)},
                                       evidence=[ev("ALL_CONSTRAINTS", "no FK on this column")]))
        for c in t["hidden_columns"]:
            if not c["virtual"] and not c["user_generated"]:
                out.append(finding("obs_hidden_system_column", "verified", severity="review", table=name,
                                   column=c["name"], params={"type": type_label(c)},
                                   evidence=[ev("ALL_TAB_COLS", "HIDDEN_COLUMN=YES, VIRTUAL_COLUMN=NO, USER_GENERATED=NO")]))

    for r in rels:
        src = r["source_table"]
        indexed = any(ix["columns"] and [c["name"] for c in ix["columns"][:len(r["source_columns"])]] == r["source_columns"]
                      for ix in tables[src]["indexes"])
        if not indexed:
            out.append(finding("obs_unindexed_fk", "verified", severity="review", table=src,
                               params={"columns": r["source_columns"], "target": r["target_table"], "constraint": r["constraint"]},
                               evidence=[ev("ALL_IND_COLUMNS", "no index whose leading columns match the FK")]))
        if r["external"]:
            out.append(finding("q_external_fk", "question", severity="review", table=src,
                               params={"constraint": r["constraint"], "owner": r["target_owner"]},
                               evidence=[ev("ALL_CONSTRAINTS.R_OWNER", r["target_owner"])]))
            continue
        for sc, tc in zip(r["source_columns"], r["target_columns"]):
            a, b = col(src, sc), col(r["target_table"], tc)
            if a and b and type_key(a) != type_key(b):
                out.append(finding("obs_fk_type_mismatch", "verified", severity="review", table=src, column=sc,
                                   params={"constraint": r["constraint"], "src_type": type_label(a),
                                           "target": f"{r['target_table']}.{tc}", "target_type": type_label(b)},
                                   evidence=[ev("ALL_TAB_COLS", "DATA_TYPE/PRECISION/SCALE/LENGTH")]))

    # ---- questions for documentation gaps ----
    for name, t in tables.items():
        if not t["comment"]:
            out.append(finding("q_no_table_comment", "question", table=name,
                               evidence=[ev("ALL_TAB_COMMENTS", "COMMENTS is NULL")]))
        if not pk_of(name):
            out.append(finding("q_no_pk", "question", table=name,
                               evidence=[ev("ALL_CONSTRAINTS", "no primary key")]))

    order = {"verified": 0, "inferred": 1, "question": 2}
    out.sort(key=lambda f: (order[f["kind"]], f["code"], f["table"] or "", f["column"] or "",
                            repr(sorted(f["params"].items()))))
    return out

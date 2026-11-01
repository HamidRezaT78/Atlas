"""Coverage validation: every discovered object must be accounted for in the outputs."""


def _item(discovered, independent, in_document, in_erd, require_document, require_erd):
    missing = set()
    if require_document and in_document is not None:
        missing |= discovered - in_document
    if require_erd and in_erd is not None:
        missing |= discovered - in_erd
    ok = not missing and (independent is None or independent == len(discovered))
    if require_document and in_document is None:
        ok = False
    return {
        "discovered": len(discovered),
        "independent": independent,
        "in_document": None if in_document is None else len(discovered & in_document),
        "in_erd": None if in_erd is None else len(discovered & in_erd),
        "missing": sorted(".".join(m) if isinstance(m, tuple) else m for m in missing),
        "ok": ok,
    }


def compute(snap, md_emitted, erd_emitted, detail, annotations=None):
    tables = snap["tables"]
    detailed = detail != "summary"
    d_tables = set(tables)
    d_columns = {(t, c["name"]) for t, v in tables.items() for c in v["columns"]}
    d_rels = {r["constraint"] for r in snap["relationships"]}
    d_rels_in_schema = {r["constraint"] for r in snap["relationships"] if not r["external"] and r["target_table"]}
    d_cons = {(t, c["name"]) for t, v in tables.items() for c in v["constraints"]}
    d_idx = {(t, i["name"]) for t, v in tables.items() for i in v["indexes"]}
    counts = snap.get("counts") or {}

    items = {
        "tables": _item(d_tables, counts.get("tables"), md_emitted["tables"], erd_emitted["tables"], True, True),
        "columns": _item(d_columns, counts.get("columns"), md_emitted["columns"] if detailed else None,
                         erd_emitted["columns"], detailed, True),
        "relationships": _item(d_rels, None, md_emitted["relationships"], None, True, False),
        "constraints": _item(d_cons, None, md_emitted["constraints"] if detailed else None, None, detailed, False),
        "indexes": _item(d_idx, None, md_emitted["indexes"] if detailed else None, None, detailed, False),
    }
    missing_erd_rels = d_rels_in_schema - erd_emitted["relationships"]
    if missing_erd_rels:
        items["relationships"]["ok"] = False
        items["relationships"]["missing"] += sorted(missing_erd_rels)
    items["relationships"]["in_erd"] = len(d_rels_in_schema & erd_emitted["relationships"])

    sections = snap["sections"]
    failed = sorted(k for k, v in sections.items() if v["status"] == "failed")

    all_cols = [c for v in tables.values() for c in v["columns"]]
    checks = [c for v in tables.values() for c in v["constraints"] if c["type"] == "C"]
    fbi_cols = [c for v in tables.values() for i in v["indexes"] if (i["type"] or "").startswith("FUNCTION-BASED")
                for c in i["columns"] if c["name"].startswith("SYS_NC")]
    completeness = {
        "tab_comments": (sum(1 for v in tables.values() if v["comment"]), len(tables)),
        "col_comments": (sum(1 for c in all_cols if c["comment"]), len(all_cols)),
        "check_conditions": (sum(1 for c in checks if c.get("condition")), len(checks)),
        "fbi_expressions": (sum(1 for c in fbi_cols if c["expression"]), len(fbi_cols)),
    }

    unmatched = []
    for t in (annotations or {}).get("tables", {}):
        if t not in tables:
            unmatched.append(t)
    for tc in (annotations or {}).get("columns", {}):
        t, _, c = tc.partition(".")
        if (t, c) not in d_columns:
            unmatched.append(tc)

    passed = all(i["ok"] for i in items.values()) and not failed
    return {
        "passed": passed,
        "detail": detail,
        "items": items,
        "failed_sections": failed,
        "sections": sections,
        "completeness": completeness,
        "annotations_unmatched": sorted(unmatched),
        "tables_without_comment": sorted(t for t, v in tables.items() if not v["comment"]),
        "columns_without_comment": sum(1 for c in all_cols if not c["comment"]),
    }

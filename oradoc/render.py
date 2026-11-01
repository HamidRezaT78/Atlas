"""Markdown and Mermaid rendering. Output is a pure function of (snapshot, findings, options)."""
import re
from collections import Counter

from .analysis import type_label
from .i18n import S, strings

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
HEADING_NUM_RE = re.compile(r"^[\d۰-۹]+\.\s*")
ERD_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def cell(value):
    """Make a value safe inside a Markdown table cell."""
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def code(value):
    return f"`{cell(value)}`" if value not in (None, "") else ""


def erd_name(name):
    """Mermaid-safe token: NUMBER(10,0) -> NUMBER_10_0, NUMBER(*,0) -> NUMBER_ANY_0."""
    return re.sub(r"_+", "_", ERD_NAME_RE.sub("_", name.replace("*", "ANY"))).strip("_")


def index_extras(ix):
    """SQL Server INCLUDE columns and filter, appended to an index's column list (empty for Oracle)."""
    text = ""
    if ix.get("include"):
        text += " INCLUDE (" + ", ".join(f"`{c}`" for c in ix["include"]) + ")"
    if ix.get("filter"):
        text += f" WHERE {code(ix['filter'])}"
    return text


def one_line(value):
    return " ".join(str(value).split())


def hidden_flags(col):
    """Flag keys for a hidden column, taken from ALL_TAB_COLS metadata."""
    return [k for k, on in (("hidden", col["hidden"]), ("virtual", col["virtual"]),
                            ("system", not col["user_generated"])) if on]


def index_hidden_links(table):
    """(index, index column, hidden column or None) for every index column that is an
    expression or a hidden column — e.g. a function-based index on SYS_NC00016$."""
    hidden = {c["name"]: c for c in table["hidden_columns"]}
    links = []
    for ix in table["indexes"]:
        for c in ix["columns"]:
            if c["expression"] or c["name"] in hidden:
                links.append((ix, c, hidden.get(c["name"])))
    return links


# ---------------------------------------------------------------------------
# ERD
# ---------------------------------------------------------------------------

def render_erd(snap):
    """Full Mermaid erDiagram: every table with every visible column, plus every in-schema FK."""
    emitted = {"tables": set(), "columns": set(), "relationships": set()}
    lines = ["erDiagram"]
    tables = snap["tables"]
    for name, t in tables.items():
        pk = next((c["columns"] for c in t["constraints"] if c["type"] == "P"), [])
        uk = {col for c in t["constraints"] if c["type"] == "U" for col in c["columns"]}
        fk = {col for c in t["constraints"] if c["type"] == "R" for col in c["columns"]}
        lines.append(f"    {erd_name(name)} {{")
        for c in t["columns"]:
            keys = [k for k, on in (("PK", c["name"] in pk), ("FK", c["name"] in fk), ("UK", c["name"] in uk)) if on]
            ty = erd_name(type_label(c))
            lines.append(f"        {ty} {erd_name(c['name'])}{(' ' + ', '.join(keys)) if keys else ''}")
            emitted["columns"].add((name, c["name"]))
        lines.append("    }")
        emitted["tables"].add(name)
    for r in snap["relationships"]:
        if r["external"] or not r["target_table"]:
            continue
        nullable = any(c["nullable"] for c in tables[r["source_table"]]["columns"] if c["name"] in r["source_columns"])
        card = "}o--o|" if nullable else "}o--||"
        lines.append(f'    {erd_name(r["source_table"])} {card} {erd_name(r["target_table"])} : '
                     f'"{"+".join(r["source_columns"])}"')
        emitted["relationships"].add(r["constraint"])
    # Mermaid has no index notation; keep function-based index links as comments so hidden
    # system columns are documented without being drawn as application columns.
    for name, t in tables.items():
        for ix, c, h in index_hidden_links(t):
            expr = c["expression"] or (h["default"] if h else None)
            lines.append(
                f"    %% index {name}.{ix['name']} ({ix['type']}, {ix['uniqueness']}) column {c['position']}: "
                f"{c['name']}"
                + (f" [hidden system column: {', '.join(S['en']['hidden_flags'][k] for k in hidden_flags(h))}; "
                   f"{type_label(h)}]" if h else "")
                + (f" = {one_line(expr)}" if expr else " = expression not collected"))
    return "\n".join(lines) + "\n", emitted


def relationship_erd(snap):
    lines = ["```mermaid", "erDiagram"]
    tables = snap["tables"]
    for r in snap["relationships"]:
        if r["external"] or not r["target_table"]:
            continue
        nullable = any(c["nullable"] for c in tables[r["source_table"]]["columns"] if c["name"] in r["source_columns"])
        card = "}o--o|" if nullable else "}o--||"
        lines.append(f'    {erd_name(r["source_table"])} {card} {erd_name(r["target_table"])} : '
                     f'"{"+".join(r["source_columns"])}"')
    lines.append("```")
    return lines


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

class Doc:
    def __init__(self, lang, audience="technical", engine=None):
        self.s = strings(lang, engine)
        self.lang = lang
        self.client = audience == "client"
        self.lines = []
        self.n = 0

    def w(self, line=""):
        self.lines.append(line)

    def num(self, value):
        return str(value).translate(FA_DIGITS) if self.lang == "fa" else str(value)

    def h2(self, key):
        self.n += 1
        title = HEADING_NUM_RE.sub("", self.s[key])
        self.w(f"## {self.num(self.n)}. {title}")
        self.w()

    def table(self, header, rows):
        self.w("| " + " | ".join(header) + " |")
        self.w("|" + "---|" * len(header))
        for r in rows:
            self.w("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
        self.w()

    def join(self, items):
        return self.s["list_sep"].join(items)

    def finding_text(self, f):
        s = self.s
        p = dict(f["params"])
        p.setdefault("table", f["table"])
        p.setdefault("column", f["column"])
        for key, value in p.items():
            if isinstance(value, int) and not isinstance(value, bool):
                p[key] = self.num(value)
        for key in ("tables",):
            if key in p:
                p[key] = self.join(f"`{x}`" for x in p[key])
        for key in ("values", "columns", "constraints"):
            if key in p and isinstance(p[key], list):
                p[key] = self.join(f"`{x}`" for x in p[key])
        if f["code"] == "inf_match_link":
            p["unique_text"] = s["f"]["inf_match_unique_yes" if p.get("unique") else "inf_match_unique_no"]
        return s["f"][f["code"]].format(**p)

    def human(self, text):
        """A user-provided annotation, labelled for the edition's readers."""
        label = self.s["client_human"] if self.client else self.s["tag"]["human"]
        return f"{label} {text}"

    def tagged(self, f, with_evidence):
        if self.client:
            # client edition: no label legend, so no tags or evidence; interpretations stay marked
            text = self.finding_text(f)
            return f"{self.s['client_inferred']} {text}" if f["kind"] == "inferred" else text
        text = f"{self.s['tag'][f['kind']]} {self.finding_text(f)}"
        if with_evidence and f["evidence"]:
            ev = "; ".join(f"{e['source']}: {e['detail']}" for e in f["evidence"])
            text += f" — _{self.s['evidence']}: {cell(ev)}_"
        return text


def render_markdown(snap, findings, *, lang, detail, erd_filename, annotations=None, audience="technical"):
    """Return (markdown_without_coverage, emitted, doc) so coverage can be appended afterwards.

    audience="client" omits the label legend, the keys/indexes summaries, structural analysis,
    DBA review, open questions and (in build) the coverage report; per-table sections stay complete.
    """
    d = Doc(lang, audience, snap.get("engine"))
    s = d.s
    tables = snap["tables"]
    rels = snap["relationships"]
    full = detail == "full"
    emitted = {"tables": set(), "columns": set(), "relationships": set(), "constraints": set(), "indexes": set()}
    ann_tables = (annotations or {}).get("tables", {})
    ann_columns = (annotations or {}).get("columns", {})

    by_table = {}
    for f in findings:
        by_table.setdefault(f["table"], []).append(f)
    out_by = {t: [r for r in rels if r["source_table"] == t] for t in tables}
    in_by = {t: [r for r in rels if r["target_table"] == t and not r["external"]] for t in tables}

    def pk_of(t):
        return next((c for c in tables[t]["constraints"] if c["type"] == "P"), None)

    sections = snap.get("sections") or {}

    def comment_text(value, section):
        """A recorded comment, a confirmed NULL comment, or a section that was not collected."""
        if value:
            return cell(value)
        if (sections.get(section) or {}).get("status") == "ok":
            return s["no_comment"]
        return s["not_collected"]

    def index_col_text(table, c):
        hidden = {h["name"] for h in table["hidden_columns"]}
        text = code(c["expression"]) if c["expression"] else f"`{c['name']}`"
        if c["name"] in hidden:
            text += f" ({s['hidden_ref'].format(name=c['name'])})"
        elif not c["expression"] and c["descend"] == "DESC":
            text += " DESC"
        return text

    # ---- header ----
    d.w(f"# {s['title'].format(schema=snap['schema'])}")
    d.w()
    d.w(f"- **{s['meta_profile']}:** `{snap['profile']}`")
    d.w(f"- **{s['meta_fingerprint']}:** `{snap['fingerprint']}`")
    d.w(f"- **{s['meta_detail']}:** {s['detail_names'][detail]}")
    if snap.get("db_version"):
        oracle = [v for v in snap["db_version"] if (v["product"] or "").startswith("Oracle")]
        d.w(f"- **{s['meta_version']}:** " + d.join(f"{v['version']}" for v in (oracle or snap["db_version"])[:1]))
    d.w(f"- **{s['meta_source']}:** {s['source_text']}")
    if d.client:
        d.w(f"- **{s['meta_audience']}:** {s['audience_names']['client']}")
    d.w()
    if not d.client:
        d.w(f"> **{s['legend_title']}**")
        d.w(">")
        for item in s["legend"]:
            d.w(f"> - {item}")
        d.w()

    # ---- overview ----
    all_cols = [c for t in tables.values() for c in t["columns"]]
    checks = [c for t in tables.values() for c in t["constraints"] if c["type"] == "C"]
    idx = [ix for t in tables.values() for ix in t["indexes"]]
    d.h2("h_overview")
    ov = s["ov"]
    d.table([s["ov_metric"], s["ov_value"]], [
        (ov["tables"], d.num(len(tables))),
        (ov["columns"], d.num(len(all_cols))),
        (ov["hidden"], d.num(sum(len(t["hidden_columns"]) for t in tables.values()))),
        (ov["pk"], d.num(sum(1 for t in tables if pk_of(t)))),
        (ov["no_pk"], d.num(sum(1 for t in tables if not pk_of(t)))),
        (ov["fk"], d.num(len(rels))),
        (ov["uk"], d.num(sum(1 for t in tables.values() for c in t["constraints"] if c["type"] == "U"))),
        (ov["checks"], f"{d.num(sum(1 for c in checks if not c.get('is_not_null')))} / {d.num(len(checks))}"),
        (ov["indexes"], d.num(len(idx))),
        (ov["fbi"], d.num(sum(1 for ix in idx if (ix["type"] or "").startswith("FUNCTION-BASED")))),
        (ov["tab_comments"], f"{d.num(sum(1 for t in tables.values() if t['comment']))} / {d.num(len(tables))}"),
        (ov["col_comments"], f"{d.num(sum(1 for c in all_cols if c['comment']))} / {d.num(len(all_cols))}"),
        (ov["defaults"], d.num(sum(1 for c in all_cols if c["default"] is not None))),
        (ov["identity"], d.num(sum(1 for c in all_cols if c["identity"]))),
        (ov["isolated"], d.num(sum(1 for t in tables if not out_by[t] and not in_by[t]))),
    ])

    # ---- table list ----
    d.h2("h_tables")
    rows = []
    for i, (name, t) in enumerate(tables.items(), 1):
        pk = pk_of(name)
        link = f"[`{name}`](#{name.lower()})" if detail != "summary" else f"`{name}`"
        rows.append((d.num(i), link, d.num(len(t["columns"])), d.join(pk["columns"]) if pk else s["missing"],
                     d.num(len(out_by[name])), d.num(len(in_by[name])), d.num(len(t["indexes"])),
                     comment_text(t["comment"], "table_comments")))
        emitted["tables"].add(name)
    d.table(s["tl_cols"], rows)

    # ---- relationships + ERD ----
    d.h2("h_relationships")
    if rels:
        rows = []
        for i, r in enumerate(rels, 1):
            nullable = any(c["nullable"] for c in tables[r["source_table"]]["columns"] if c["name"] in r["source_columns"])
            target = r["target_table"] or f"{r['target_owner']}.?"
            rows.append((d.num(i), f"`{r['source_table']}`", d.join(f"`{c}`" for c in r["source_columns"]),
                         f"`{target}`", d.join(f"`{c}`" for c in r["target_columns"]) or s["unknown"],
                         s["yes"] if nullable else s["no"], r["delete_rule"] or s["none"], f"`{r['constraint']}`"))
            emitted["relationships"].add(r["constraint"])
        d.table(s["rel_cols"], rows)
        d.w(s["erd_note_client"] if d.client else s["erd_note"].format(erd=erd_filename))
        d.w()
        d.lines.extend(relationship_erd(snap))
        d.w()
    else:
        d.w(s["no_relationships"])
        d.w()

    # ---- per-table details ----
    if detail != "summary":
        d.h2("h_details")
        for name, t in tables.items():
            d.w(f"### {name}")
            d.w()
            d.w(f"**{s['desc']}**")
            d.w()
            desc = [f for f in by_table.get(name, [])
                    if f["code"] in ("tab_comment", "inf_lookup", "inf_copy_of", "inf_match_link",
                                     "tab_referenced_by", "tab_references")]
            ann = ann_tables.get(name)
            if desc or ann:
                for f in desc:
                    d.w(f"- {d.tagged(f, full)}")
                if ann:
                    d.w(f"- {d.human(cell(ann['text']))}"
                        + (f" — _{cell(ann.get('source'))}_" if ann.get("source") else ""))
            else:
                d.w(f"- {s['no_desc']}")
            d.w()

            pk = pk_of(name)
            pk_cols = pk["columns"] if pk else []
            fk_cols = {c for r in out_by[name] for c in r["source_columns"]}
            uk_cols = {c for k in t["constraints"] if k["type"] == "U" for c in k["columns"]}
            rows = []
            for i, c in enumerate(t["columns"], 1):
                keys = [k for k, on in (("PK", c["name"] in pk_cols), ("FK", c["name"] in fk_cols),
                                        ("UK", c["name"] in uk_cols)) if on]
                comment = comment_text(c["comment"], "column_comments")
                annc = ann_columns.get(f"{name}.{c['name']}")
                if annc:
                    comment += f" {d.human(cell(annc['text']))}"
                rows.append((d.num(i), f"`{c['name']}`", code(type_label(c)),
                             s["yes"] if c["nullable"] else s["no"],
                             code(c["default"]) if c["default"] is not None else s["none"],
                             " ".join(keys), comment))
                emitted["columns"].add((name, c["name"]))
            d.table(s["col_cols"], rows)

            col_notes = [f for f in by_table.get(name, [])
                         if f["code"] in ("chk_allowed_values", "chk_condition", "inf_flag", "inf_enum")]
            for f in col_notes:
                d.w(f"- {d.tagged(f, full)}")
            if col_notes:
                d.w()

            d.w(f"**{s['pk']}:** " + (f"`{pk['name']}` ({d.join(f'`{c}`' for c in pk['columns'])})"
                                      if pk else s["no_pk_defined"]))
            d.w()
            if pk:
                emitted["constraints"].add((name, pk["name"]))
            uks = [k for k in t["constraints"] if k["type"] == "U"]
            if uks:
                d.w(f"**{s['uk']}:** " + d.join(f"`{k['name']}` ({d.join(f'`{c}`' for c in k['columns'])})" for k in uks))
                d.w()
                emitted["constraints"].update((name, k["name"]) for k in uks)
            if out_by[name]:
                d.w(f"**{s['fk_out']}:**")
                d.w()
                for r in out_by[name]:
                    target = r["target_table"] or f"{r['target_owner']}.?"
                    d.w(f"- {d.join(f'`{c}`' for c in r['source_columns'])} → `{target}`"
                        f"({d.join(f'`{c}`' for c in r['target_columns'])}) — `{r['constraint']}`"
                        + (f", ON DELETE {r['delete_rule']}" if full and r["delete_rule"] else ""))
                    emitted["constraints"].add((name, r["constraint"]))
                d.w()
            if in_by[name]:
                d.w(f"**{s['fk_in']}:** " + d.join(f"`{r['source_table']}`.{d.join(f'`{c}`' for c in r['source_columns'])}"
                                                    for r in in_by[name]))
                d.w()
            real_checks = [k for k in t["constraints"] if k["type"] == "C" and not k.get("is_not_null")]
            nn_checks = [k for k in t["constraints"] if k["type"] == "C" and k.get("is_not_null")]
            if real_checks:
                d.w(f"**{s['checks']}:** " + d.join(f"`{k['name']}`: `{cell(k.get('condition')) or s['unknown']}`"
                                                    for k in real_checks))
                d.w()
            if nn_checks and full:
                d.w(f"**{s['not_null_checks']}:** " + d.join(f"`{k['columns'][0] if k['columns'] else '?'}`"
                                                             for k in nn_checks))
                d.w()
            emitted["constraints"].update((name, k["name"]) for k in real_checks + nn_checks)

            if t["indexes"]:
                rows = []
                for ix in t["indexes"]:
                    parts = [index_col_text(t, c) for c in ix["columns"]]
                    state = ix["status"] + (f"/{ix['visibility']}" if ix.get("visibility") and full else "")
                    rows.append((f"`{ix['name']}`", ix["type"], s["yes"] if ix["uniqueness"] == "UNIQUE" else s["no"],
                                 d.join(parts) + index_extras(ix), state))
                    emitted["indexes"].add((name, ix["name"]))
                d.table(s["idx_cols"], rows)
            else:
                d.w(s["no_indexes"])
                d.w()
            hidden_links = [(ix, c, h) for ix, c, h in index_hidden_links(t) if h]
            if hidden_links:
                d.w(f"**{s['idx_hidden_cols']}:**")
                d.w()
                for ix, c, h in hidden_links:
                    expr = c["expression"] or h["default"]
                    d.w("- " + s["hidden_used_by"].format(
                        name=h["name"], flags=d.join(s["hidden_flags"][k] for k in hidden_flags(h)),
                        type=type_label(h), expr=code(expr) if expr else s["not_collected"],
                        index=ix["name"], pos=d.num(c["position"])))
                d.w()
            if full and t["hidden_columns"]:
                d.w(f"**{s['hidden_cols']}:** " + d.join(
                    f"`{c['name']}` ({type_label(c)}" + (f", `{cell(c['default'])}`" if c["default"] else "") + ")"
                    for c in t["hidden_columns"]))
                d.w()

    if detail != "summary" and not d.client:
        # ---- keys & constraints summary ----
        d.h2("h_keys")
        rows = []
        for name, t in tables.items():
            for k in t["constraints"]:
                if k["type"] == "C" and k.get("is_not_null") and not full:
                    continue
                if k["type"] == "R":
                    det = next((f"→ `{r['target_table'] or r['target_owner'] + '.?'}`" for r in rels
                                if r["constraint"] == k["name"]), "")
                elif k["type"] == "C":
                    det = code(k.get("condition")) or s["unknown"]
                else:
                    det = f"`{k['index_name']}`" if k.get("index_name") else ""
                state = f"{k['status']}/{k['validated']}"
                rows.append((f"`{name}`", f"`{k['name']}`", s["cons_type"][k["type"]],
                             d.join(f"`{c}`" for c in k["columns"]), det, state))
        d.table(s["cons_cols"], rows)

        # ---- index summary ----
        d.h2("h_indexes")
        rows = []
        for name, t in tables.items():
            for ix in t["indexes"]:
                parts = [index_col_text(t, c) for c in ix["columns"]]
                rows.append((f"`{name}`.`{ix['name']}`", ix["type"], s["yes"] if ix["uniqueness"] == "UNIQUE" else s["no"],
                             d.join(parts) + index_extras(ix), ix["status"]))
        d.table(s["idx_cols"], rows)

    if d.client:
        return d, emitted

    # ---- structural analysis ----
    d.h2("h_analysis")
    obs = [f for f in findings if f["code"].startswith("obs_")]
    counts = Counter(f["code"] for f in obs)
    d.w(f"**{s['an_counts']}**")
    d.w()
    d.table(s["an_cols"], [(s["code_titles"][c], d.num(n)) for c, n in sorted(counts.items())])
    for f in obs:
        if f["severity"] == "info":
            d.w(f"- {d.tagged(f, full)}")
    inferred_global = [f for f in findings if f["kind"] == "inferred"]
    if inferred_global:
        d.w()
        for f in inferred_global:
            d.w(f"- `{f['table']}`: {d.tagged(f, True)}")
    d.w()

    # ---- DBA review ----
    d.h2("h_dba")
    review = [f for f in findings if f["severity"] == "review"]
    if review:
        for f in review:
            d.w(f"- {d.tagged(f, full)}")
    else:
        d.w(s["dba_none"])
    d.w()

    # ---- open questions ----
    d.h2("h_questions")
    qs = [f for f in findings if f["kind"] == "question"]
    if not qs:
        d.w(s["q_none"])
        d.w()
    for group, title in s["q_groups"].items():
        items = [f for f in qs if f["code"] == group]
        if not items:
            continue
        d.w(f"### {title} ({d.num(len(items))})")
        d.w()
        for f in items:
            d.w(f"- {d.finding_text(f)}")
        d.w()

    return d, emitted


def render_coverage(d, coverage):
    if d.client:  # the client edition carries no coverage report (it is still written as JSON)
        return "\n".join(d.lines).rstrip() + "\n"
    s = d.s
    d.h2("h_coverage")
    d.w(s["cov_result_pass"] if coverage["passed"] else s["cov_result_fail"])
    d.w()
    rows = []
    for key, item in coverage["items"].items():
        md = d.num(item["in_document"]) if item["in_document"] is not None else s["cov_not_rendered"]
        erd = d.num(item["in_erd"]) if item["in_erd"] is not None else s["none"]
        ind = d.num(item["independent"]) if item["independent"] is not None else s["none"]
        rows.append((s["cov_items"][key], d.num(item["discovered"]), ind, md, erd,
                     s["cov_ok"] if item["ok"] else s["cov_fail"]))
    d.table(s["cov_cols"], rows)
    for key, item in coverage["items"].items():
        if item["missing"]:
            d.w(f"- **{s['cov_items'][key]} — {s['cov_missing_list']}:** "
                + d.join(f"`{m}`" for m in item["missing"][:50])
                + (" …" if len(item["missing"]) > 50 else ""))
    d.w()
    d.w(f"**{s['cov_sections']}**")
    d.w()
    d.table(s["cov_section_cols"], [(f"`{k}`", s["cov_status"][v["status"]], cell(v.get("error")) or s["none"])
                                    for k, v in coverage["sections"].items()])
    d.w(f"**{s['cov_completeness']}**")
    d.w()
    d.table([s["ov_metric"], s["ov_value"]], [(s["ov"][k] if k in s["ov"] else k, f"{d.num(a)} / {d.num(b)}")
                                              for k, (a, b) in coverage["completeness"].items()])
    if coverage["annotations_unmatched"]:
        d.w(f"**{s['cov_annotations_unmatched']}:** " + d.join(f"`{x}`" for x in coverage["annotations_unmatched"]))
        d.w()
    return "\n".join(d.lines).rstrip() + "\n"

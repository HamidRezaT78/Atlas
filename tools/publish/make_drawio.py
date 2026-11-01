"""Build an editable draw.io ERD from an oradoc snapshot, using Mermaid's layout for table positions.

Usage: python make_drawio.py <snapshot.json> <nodes.json> <erd.mmd> <out.drawio>  (or build() from publish.py)
Tables are stack-layout containers (one row per visible column); FK edges connect the FK column row
to the referenced column row with ER cardinality arrows. %% index notes from the .mmd become note shapes.
"""
import json
import re
import sys
from xml.sax.saxutils import escape

HEADER, MIN_ROW = 30, 22


def a(v):
    return escape(str(v), {'"': "&quot;", "\n": "&#10;"})


def type_label(c):
    t = c["data_type"]
    if t in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "RAW"):
        if c.get("char_used") == "C" and c.get("char_length"):
            return f"{t}({c['char_length']} CHAR)"
        return f"{t}({c['data_length']})"
    if t == "NUMBER":
        p, s = c["data_precision"], c["data_scale"]
        if p is None and s is None:
            return "NUMBER"
        return f"NUMBER(*,{s})" if p is None else f"NUMBER({p},{s})"
    return t


def build(snap_path, nodes, mmd_path, out_path):
    """nodes: Mermaid node boxes [{x, y, w, h, texts}] of the full ERD. Writes out_path (never overwrites)."""
    snap = json.load(open(snap_path, encoding="utf-8"))
    tables = snap["tables"]
    # table name -> Mermaid box (the entity name is one of the texts in the node)
    box = {}
    for n in nodes:
        name = next((t for t in n["texts"] if t in tables), None)
        if name:
            box[name] = n
    missing = sorted(set(tables) - set(box))
    if missing:
        raise ValueError(f"no layout position for: {missing}")

    cells, ids = [], {}
    cells.append('<mxCell id="0"/>')
    cells.append('<mxCell id="1" parent="0"/>')
    for name, t in tables.items():
        b = box[name]
        pk = next((c["columns"] for c in t["constraints"] if c["type"] == "P"), [])
        fk = {col for c in t["constraints"] if c["type"] == "R" for col in c["columns"]}
        uk = {col for c in t["constraints"] if c["type"] == "U" for col in c["columns"]}
        n = max(1, len(t["columns"]))
        row_h = max(MIN_ROW, int((b["h"] - HEADER) / n))
        width = max(int(b["w"]), 260)
        tid = f"t_{name}"
        ids[name] = tid
        cells.append(
            f'<mxCell id="{tid}" value="{a(name)}" style="swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;'
            f'startSize={HEADER};horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=1;'
            f'marginBottom=0;fillColor=#dae8fc;strokeColor=#6c8ebf;align=center;fontSize=12;" vertex="1" parent="1">'
            f'<mxGeometry x="{int(b["x"])}" y="{int(b["y"])}" width="{width}" height="{HEADER + row_h * n}" as="geometry"/></mxCell>')
        for i, c in enumerate(t["columns"]):
            keys = [k for k, on in (("PK", c["name"] in pk), ("FK", c["name"] in fk), ("UK", c["name"] in uk)) if on]
            label = f"{c['name']} : {type_label(c)}" + (f"   [{', '.join(keys)}]" if keys else "") + ("" if c["nullable"] else "  NOT NULL")
            rid = f"c_{name}_{c['name']}"
            ids[(name, c["name"])] = rid
            bold = "fontStyle=1;" if "PK" in keys else ""
            cells.append(
                f'<mxCell id="{a(rid)}" value="{a(label)}" style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;'
                f'spacingLeft=6;spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;'
                f'fontFamily=Consolas;fontSize=11;{bold}" vertex="1" parent="{tid}">'
                f'<mxGeometry y="{HEADER + i * row_h}" width="{width}" height="{row_h}" as="geometry"/></mxCell>')

    edges = 0
    for r in snap["relationships"]:
        if r["external"] or not r["target_table"]:
            continue
        src_t, dst_t = r["source_table"], r["target_table"]
        src_col, dst_col = r["source_columns"][0], r["target_columns"][0]
        nullable = any(c["nullable"] for c in tables[src_t]["columns"] if c["name"] in r["source_columns"])
        end = "ERzeroToOne" if nullable else "ERmandOne"
        eid = f"e_{r['constraint']}"
        cells.append(
            f'<mxCell id="{a(eid)}" value="{a("+".join(r["source_columns"]))}" style="edgeStyle=entityRelationEdgeStyle;html=0;'
            f'startArrow=ERzeroToMany;startFill=0;endArrow={end};endFill=0;fontSize=10;labelBackgroundColor=#ffffff;" '
            f'edge="1" parent="1" source="{a(ids[(src_t, src_col)])}" target="{a(ids[(dst_t, dst_col)])}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>')
        edges += 1

    notes = 0
    for line in open(mmd_path, encoding="utf-8"):
        m = re.match(r"\s*%% index ([A-Z0-9_$#]+)\.(\S+) (.*)$", line.rstrip("\n"))
        if not m:
            continue
        table = m.group(1)
        b = box[table]
        notes += 1
        text = f"index {table}.{m.group(2)} {m.group(3)}"
        cells.append(
            f'<mxCell id="n_{notes}" value="{a(text)}" style="shape=note;whiteSpace=wrap;size=14;align=left;spacingLeft=8;'
            f'fillColor=#fff2cc;strokeColor=#d6b656;fontSize=10;fontFamily=Consolas;" vertex="1" parent="1">'
            f'<mxGeometry x="{int(b["x"])}" y="{int(b["y"] + b["h"] + 30)}" width="{max(int(b["w"]), 520)}" height="70" as="geometry"/></mxCell>')
        cells.append(
            f'<mxCell id="nl_{notes}" style="endArrow=none;dashed=1;strokeColor=#d6b656;" edge="1" parent="1" '
            f'source="n_{notes}" target="{ids[table]}"><mxGeometry relative="1" as="geometry"/></mxCell>')

    xml = ('<mxfile host="oradoc" type="device">'
           f'<diagram id="erd" name="{a(snap["schema"])} ERD">'
           '<mxGraphModel dx="1600" dy="1200" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
           'fold="1" page="0" pageScale="1" math="0" shadow="0"><root>'
           + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>\n")
    with open(out_path, "x", encoding="utf-8") as f:  # "x": never overwrite
        f.write(xml)
    return (f"{out_path}: tables={len(tables)} columns={sum(len(t['columns']) for t in tables.values())} edges={edges} notes={notes}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(build(sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8-sig")), sys.argv[3], sys.argv[4]))

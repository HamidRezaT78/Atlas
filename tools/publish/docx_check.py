"""Compare an oradoc Markdown source with its .docx: headings, tables (cell by cell), paragraphs,
code identifiers, text direction, TOC and page-number fields. Read-only.

Usage: python docx_check.py <source.md> <document.docx> <fa|en> [--mermaid-image]  (or check() from publish.py)
--mermaid-image: the ```mermaid block was replaced by a picture (client edition); its code lines are not
expected in the document and a picture must be present instead."""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def norm(s):
    for mark in ("‎", "‪", "‬", "‭", "⁦", "⁩"):
        s = s.replace(mark, "")
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def plain(s):
    s = re.sub(r" — _(.+)_$", r" — \1", s)
    s = re.sub(r"\[((?:`[^`]*`|[^\]`])*)\]\(#[^)\s]+\)", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    return norm(s.replace("**", ""))


def split_row(line):
    body = line.strip()[1:-1]
    return [c.strip().replace("\\|", "|").replace("\\\\", "\\") for c in re.split(r"(?<!\\)\|", body)]


def check(md_path, docx_path, lang, mermaid_image=False):
    md_path, docx_path = str(md_path), str(docx_path)
    # ---- markdown model ----
    lines = open(md_path, encoding="utf-8").read().split("\n")
    md_head, md_tables, md_paras, md_code = [], [], [], []
    i = 0
    while i < len(lines):
        l = lines[i]
        if re.match(r"^#{1,3} ", l):
            md_head.append(plain(l.split(" ", 1)[1]))
        elif l.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[-:| ]+\|$", lines[i]):
                    rows.append([plain(c) for c in split_row(lines[i])])
                i += 1
            md_tables.append(rows)
            continue
        elif l.startswith("```"):
            skip = mermaid_image and l.strip() == "```mermaid"
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                if not skip:
                    md_paras.append(norm(lines[i]))
                i += 1
        elif l.startswith(">"):
            body = l[1:].lstrip()
            body = body[2:] if body.startswith("- ") else body
            if body:
                md_paras.append(plain(body))
        elif l.startswith("- "):
            md_paras.append(plain(l[2:]))
        elif l.strip():
            md_paras.append(plain(l))
        md_code.extend(m for m in re.findall(r"`([^`]*)`", l))
        i += 1

    # ---- docx model ----
    z = zipfile.ZipFile(docx_path)
    doc = ET.fromstring(z.read("word/document.xml"))
    body = doc.find(W + "body")


    def ptext(p):
        return norm("".join(t.text or "" for t in p.iter(W + "t")))


    def pstyle(p):
        s = p.find(f"{W}pPr/{W}pStyle")
        return s.get(W + "val") if s is not None else ""


    dx_paras, dx_heads, dx_tables, bidi_paras, total_paras, toc_entries = [], [], [], 0, 0, 0
    for el in body:
        if el.tag == W + "p":
            total_paras += 1
            bidi_paras += el.find(f"{W}pPr/{W}bidi") is not None
            st = pstyle(el)
            if st.upper().startswith("TOC") and st.upper() != "TOCHEADING":
                toc_entries += 1
                continue
            if st in ("Title", "Heading1", "Heading2"):
                dx_heads.append(ptext(el))
            dx_paras.append(ptext(el))
        elif el.tag == W + "tbl":
            rows = []
            for tr in el.findall(W + "tr"):
                rows.append([norm(" ".join(ptext(p) for p in tc.iter(W + "p"))) for tc in tr.findall(W + "tc")])
            dx_tables.append((rows, el.find(f"{W}tblPr/{W}bidiVisual") is not None))

    all_text = norm(" ".join(dx_paras + [c for rows, _ in dx_tables for r in rows for c in r]))

    # ---- comparisons ----
    problems = []
    missing_heads = [h for h in md_head if h not in dx_heads]
    if len(dx_tables) != len(md_tables):
        problems.append(f"table count md={len(md_tables)} docx={len(dx_tables)}")
    cell_mismatch = row_mismatch = 0
    for ti, (mt, (dt, _)) in enumerate(zip(md_tables, dx_tables)):
        if len(mt) != len(dt):
            row_mismatch += 1
            problems.append(f"table {ti + 1}: rows md={len(mt)} docx={len(dt)}")
            continue
        for r, (mr, dr) in enumerate(zip(mt, dt)):
            for c, (mc, dc) in enumerate(zip(mr, dr)):
                if mc != dc:
                    cell_mismatch += 1
                    if cell_mismatch <= 5:
                        problems.append(f"table {ti + 1} r{r + 1} c{c + 1}: md={mc!r} docx={dc!r}")
    para_counter = Counter(dx_paras)
    missing_paras = []
    for p in md_paras:
        if para_counter[p] > 0:
            para_counter[p] -= 1
        else:
            missing_paras.append(p)
    missing_code = sorted({c for c in md_code if norm(c) and norm(c) not in all_text})

    sect = body.find(W + "sectPr")
    sect_bidi = sect.find(W + "bidi") is not None
    tables_rtl = sum(1 for _, rtl in dx_tables if rtl)
    footer = z.read("word/footer1.xml").decode("utf-8")
    settings_lang = re.search(r'w:bidi="([^"]+)"', z.read("word/styles.xml").decode("utf-8"))

    pictures = sum(1 for n in z.namelist() if n.startswith("word/media/"))
    if mermaid_image and not pictures:
        problems.append("relationship diagram picture missing")
    print(f"== {docx_path.split(chr(92))[-1]} ({lang})")
    print(f"   headings: md={len(md_head)} docx={len(dx_heads)} missing={len(missing_heads)} {missing_heads[:3]}")
    print(f"   tables: md={len(md_tables)} docx={len(dx_tables)} rows(md)={sum(len(t) for t in md_tables)} "
          f"rows(docx)={sum(len(t) for t, _ in dx_tables)} row-count mismatches={row_mismatch} cell mismatches={cell_mismatch}")
    print(f"   paragraphs/list items/code lines: md={len(md_paras)} missing in docx={len(missing_paras)} {missing_paras[:3]}")
    print(f"   code identifiers: distinct={len(set(md_code))} missing={len(missing_code)} {missing_code[:5]}")
    print(f"   pictures={pictures}  toc entries={toc_entries}  footer PAGE={' PAGE ' in footer} NUMPAGES={'NUMPAGES' in footer}")
    print(f"   direction: section bidi={sect_bidi} paragraphs with bidi={bidi_paras}/{total_paras} tables RTL={tables_rtl}/{len(dx_tables)}"
          f" complex-script lang={settings_lang.group(1) if settings_lang else None}")
    for p in problems[:10]:
        print("   PROBLEM:", p)
    ok = (not missing_heads and len(dx_tables) == len(md_tables) and not row_mismatch and not cell_mismatch
          and not missing_paras and not missing_code and toc_entries > 0 and (pictures > 0 or not mermaid_image))
    ok = ok and ((sect_bidi and tables_rtl == len(dx_tables)) if lang == "fa" else (not sect_bidi and tables_rtl == 0 and bidi_paras == 0))
    print("   RESULT:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(0 if check(sys.argv[1], sys.argv[2], sys.argv[3], "--mermaid-image" in sys.argv[4:]) else 1)

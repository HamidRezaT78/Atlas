"""Convert an oradoc Markdown document into a Word .docx (stdlib only, fully offline).

Usage: python md2docx.py <input.md> <output.docx> <fa|en> <SCHEMA> [relationships.png]
(or convert() from tools/publish/publish.py)

Supports exactly the Markdown that oradoc emits: # / ## / ### headings, pipe tables,
"- " bullets, "> " callouts (with "> - " bullets), ``` fences, **bold**, `code`,
[text](#anchor) internal links and the trailing " — _evidence_" italics.
Persian output: RTL section/paragraphs/tables, B Nazanin (complex script) with Tahoma
noted as alternate, LRM marks around left-to-right runs so identifiers keep their order.
"""
import datetime
import re
import sys
import zipfile
from xml.sax.saxutils import escape

SRC = OUT = IMG = None  # set by convert(); IMG is an optional PNG that replaces the ```mermaid block
LANG, SCHEMA = "fa", ""
RTL = True
LRM = "‎"
LRO, PDF = "‭", "‬"

LATIN_FONT = "Segoe UI"
CS_FONT = "B Nazanin"
CODE_FONT = "Consolas"
PAGE_W, PAGE_H, MARGIN = 16838, 11906, 1020          # A4 landscape, 1.8 cm margins
AVAIL = PAGE_W - 2 * MARGIN

TEXTS = {
    "fa": {"toc": "فهرست مطالب", "toc_hint": "برای به‌روزرسانی فهرست، روی آن راست‌کلیک کنید.",
           "page": "صفحه ", "of": " از ", "header": "مستندات دیتابیس {schema}"},
    "en": {"toc": "Contents", "toc_hint": "Right-click to update the table of contents.",
           "page": "Page ", "of": " of ", "header": "{schema} Database Documentation"},
}
T = TEXTS[LANG]

ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
LATIN = re.compile(r"[A-Za-z0-9]")
TOKEN = re.compile(r"\[((?:`[^`]*`|[^\]`])*)\]\(#([^)\s]+)\)|`([^`]*)`|\*\*")
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def x(text):
    return escape(INVALID_XML.sub("", text), {'"': "&quot;"})


# ---------------------------------------------------------------------------
# inline Markdown -> segments [(text, {bold, italic, code, link})]
# ---------------------------------------------------------------------------

def inline(text):
    tail = None
    m = re.search(r" — _(.+)_$", text)
    if m:
        tail = m.group(1)
        text = text[:m.start()] + " — "
    segs, bold, pos = [], False, 0
    for t in TOKEN.finditer(text):
        if t.start() > pos:
            segs.append((text[pos:t.start()], {"bold": bold}))
        if t.group(0) == "**":
            bold = not bold
        elif t.group(3) is not None:
            segs.append((t.group(3), {"bold": bold, "code": True}))
        else:
            for s, p in inline(t.group(1)):
                segs.append((s, dict(p, bold=bold or p.get("bold"), link=t.group(2))))
        pos = t.end()
    if pos < len(text):
        segs.append((text[pos:], {"bold": bold}))
    if tail is not None:
        segs.extend((s, dict(p, italic=True)) for s, p in inline(tail))
    return [(s, p) for s, p in segs if s]


def plain(text):
    return "".join(s for s, _ in inline(text))


# ---------------------------------------------------------------------------
# runs (with bidi handling for Persian)
# ---------------------------------------------------------------------------

def atoms(segs):
    """Split segments into direction-tagged atoms; code is always LTR."""
    out = []
    for s, p in segs:
        if p.get("code") or not RTL:
            out.append([s, p, "ltr"])
            continue
        for tok in re.findall(r"\s+|\S+", s):
            if tok.isspace():
                d = None
            elif ARABIC.search(tok):
                d = "rtl"
            elif LATIN.search(tok):
                d = "ltr"
            else:
                d = "neutral"  # punctuation only: resolved below from directly attached atoms
            out.append([tok, p, d])
    if RTL:
        for i, a in enumerate(out):
            if a[2] == "neutral":
                prev = out[i - 1] if i > 0 else None
                nxt = out[i + 1] if i + 1 < len(out) else None
                attached_ltr = any(b is not None and b[2] == "ltr" and not b[0][-1 if b is prev else 0].isspace()
                                   for b in (prev, nxt))
                a[2] = "ltr" if attached_ltr else "rtl"
        for i, a in enumerate(out):
            if a[2] is None:
                prev = next((b[2] for b in reversed(out[:i]) if b[2]), "rtl")
                nxt = next((b[2] for b in out[i + 1:] if b[2]), "rtl")
                a[2] = "ltr" if prev == nxt == "ltr" else "rtl"
    merged = []
    for a in out:
        if merged and merged[-1][1] == a[1] and merged[-1][2] == a[2]:
            merged[-1][0] += a[0]
        else:
            merged.append(list(a))
    return merged


def rpr(p, direction, size=None, size_cs=None, extra=""):
    parts = []
    if p.get("code"):
        parts.append('<w:rStyle w:val="CodeChar"/>')
    elif p.get("link"):
        parts.append('<w:rStyle w:val="Hyperlink"/>')
    if p.get("code"):
        parts.append(f'<w:rFonts w:ascii="{CODE_FONT}" w:hAnsi="{CODE_FONT}" w:cs="{CODE_FONT}"/>')
    if p.get("bold"):
        parts.append("<w:b/><w:bCs/>")
    if p.get("italic"):
        parts.append("<w:i/><w:iCs/>")
    parts.append(extra)
    if size:
        parts.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size_cs or size}"/>')
    if direction == "rtl":
        parts.append("<w:rtl/>")
    return "<w:rPr>" + "".join(parts) + "</w:rPr>"


def runs(segs, size=None, size_cs=None, extra=""):
    xml = []
    for text, p, d in atoms(segs):
        override = False
        if RTL and d == "ltr":
            strong = len(LATIN.findall(text))
            if p.get("code") and not ARABIC.search(text) and strong * 2 < len(text):
                # symbol-heavy code (e.g. "}o--||"): Word's native, scoped LTR override (w:bdo).
                override = True
            else:
                text = LRM + text + LRM
        if override:
            # one run per character, each followed by an LRM in its own (Segoe UI) run
            mark = f'<w:r><w:rPr><w:rFonts w:ascii="Segoe UI" w:hAnsi="Segoe UI" w:cs="Segoe UI"/></w:rPr><w:t>{LRM}</w:t></w:r>'
            r = mark + "".join(
                f'<w:r>{rpr(p, d, size, size_cs, extra)}<w:t xml:space="preserve">{x(ch)}</w:t></w:r>{mark}' for ch in text)
        else:
            r = f'<w:r>{rpr(p, d, size, size_cs, extra)}<w:t xml:space="preserve">{x(text)}</w:t></w:r>'
        if p.get("link"):
            r = f'<w:hyperlink w:anchor="{bookmark(p["link"])}" w:history="1">{r}</w:hyperlink>'
        xml.append(r)
    return "".join(xml)


def bookmark(anchor):
    return ("t_" + re.sub(r"[^A-Za-z0-9_]", "_", anchor))[:40]


def ppr(style=None, *, bidi=None, jc=None, num=False, extra="", keep_next=False):
    bidi = RTL if bidi is None else bidi
    parts = []
    if style:
        parts.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        parts.append("<w:keepNext/>")
    if num:
        parts.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    parts.append(extra)
    if bidi:
        parts.append("<w:bidi/>")
    elif RTL:
        parts.append('<w:bidi w:val="0"/>')  # explicit LTR inside an RTL document (code lines)
    if jc:
        parts.append(f'<w:jc w:val="{jc}"/>')
    return "<w:pPr>" + "".join(parts) + "</w:pPr>"


def para(segs, style=None, **kw):
    size = kw.pop("size", None)
    size_cs = kw.pop("size_cs", None)
    pre = kw.pop("pre", "")
    post = kw.pop("post", "")
    return f"<w:p>{ppr(style, **kw)}{pre}{runs(segs, size, size_cs)}{post}</w:p>"


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

def split_row(line):
    cells, cur, i = [], "", 0
    body = line.strip()[1:-1] if line.strip().endswith("|") else line.strip()[1:]
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] in "|\\":
            cur += body[i + 1]
            i += 2
            continue
        if ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def table(rows):
    header, body = rows[0], rows[1:]
    ncol = len(header)
    weights = []
    for c in range(ncol):
        longest = max(len(plain(r[c])) if c < len(r) else 0 for r in rows)
        weights.append(max(3, min(longest, 46)))
    total = sum(weights)
    widths = [max(560, int(AVAIL * w / total)) for w in weights]
    widths[-1] += AVAIL - sum(widths)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="DocTable"/>'
           + ("<w:bidiVisual/>" if RTL else "")
           + f'<w:tblW w:w="{AVAIL}" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
           + '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/>'
           + f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>"]
    for ri, row in enumerate([header] + body):
        row = (row + [""] * ncol)[:ncol]
        trpr = "<w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if ri == 0 else "") + "</w:trPr>"
        cells = []
        for ci, val in enumerate(row):
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="DDEBEC"/>' if ri == 0 else (
                '<w:shd w:val="clear" w:color="auto" w:fill="F6F8FA"/>' if ri % 2 == 0 else "")
            segs = inline(val)
            if ri == 0:
                segs = [(s, dict(p, bold=True)) for s, p in segs]
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[ci]}" w:type="dxa"/>{shade}</w:tcPr>'
                         + para(segs, "TableText") + "</w:tc>")
        out.append(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")
    out.append("</w:tbl>")
    out.append(para([], "AfterTable"))
    return "".join(out)


# ---------------------------------------------------------------------------
# document body
# ---------------------------------------------------------------------------

def toc_block():
    return (para([(T["toc"], {})], "TOCHeading")
            + '<w:p>' + ppr() + '<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
            + '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
            + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + f'<w:r><w:t>{x(T["toc_hint"])}</w:t></w:r>'
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')  # Heading 1 starts a new page


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG file")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def image_paragraph(path):
    """Inline picture scaled to the text area (EMU: 1 twip = 635 EMU), centred, left-to-right."""
    w, h = png_size(path)
    max_w, max_h = AVAIL * 635, (PAGE_H - 2 * MARGIN - 1600) * 635
    scale = min(max_w / w, max_h / h)
    cx, cy = int(w * scale), int(h * scale)
    return ('<w:p><w:pPr><w:spacing w:before="120" w:after="120"/><w:bidi w:val="0"/><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="Relationship diagram" descr="Relationship diagram (ERD)"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            '<pic:nvPicPr><pic:cNvPr id="1" name="erd_relationships.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="rIdImg1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:inline></w:drawing></w:r></w:p>')


def build_body(lines):
    anchors = {m for line in lines for m in re.findall(r"\]\(#([^)\s]+)\)", line)}
    out, i, bm, title, toc_done = [], 0, 0, None, False
    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            title = plain(line[2:])
            out.append(para(inline(line[2:]), "Title"))
            i += 1
        elif line.startswith("## "):
            if not toc_done:
                out.append(toc_block())
                toc_done = True
            out.append(para(inline(line[3:]), "Heading1"))
            i += 1
        elif line.startswith("### "):
            text = line[4:]
            anchor = plain(text).lower()
            if anchor in anchors:
                bm += 1
                out.append(para(inline(text), "Heading2",
                                pre=f'<w:bookmarkStart w:id="{bm}" w:name="{bookmark(anchor)}"/>',
                                post=f'<w:bookmarkEnd w:id="{bm}"/>'))
            else:
                out.append(para(inline(text), "Heading2"))
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[-:| ]+\|$", lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            out.append(table(rows))
        elif line.startswith("```"):
            is_mermaid = line.strip() == "```mermaid"
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            if is_mermaid and IMG:
                out.append(image_paragraph(IMG))
                continue
            for cl in code_lines:
                out.append(f'<w:p>{ppr("CodeBlock", bidi=False, jc="left")}<w:r><w:t xml:space="preserve">{x(cl)}</w:t></w:r></w:p>')
        elif line.startswith(">"):
            body = line[1:].lstrip()
            if body.startswith("- "):
                out.append(para(inline(body[2:]), "CalloutBullet", num=True))
            elif body:
                out.append(para(inline(body), "Callout"))
            i += 1
        elif line.startswith("- "):
            out.append(para(inline(line[2:]), "ListText", num=True))
            i += 1
        elif line.strip() == "":
            i += 1
        else:
            out.append(para(inline(line), None))
            i += 1
    return title, "".join(out)


# ---------------------------------------------------------------------------
# package parts
# ---------------------------------------------------------------------------

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def styles():
    body_sz, body_cs = (20, 24) if RTL else (20, 20)
    lang = '<w:lang w:val="en-US" w:bidi="fa-IR"/>' if RTL else '<w:lang w:val="en-US"/>'
    def pstyle(sid, name, ppr_xml="", rpr_xml="", based="Normal", nxt="Normal", extra=""):
        return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>'
                f'<w:basedOn w:val="{based}"/><w:next w:val="{nxt}"/>{extra}<w:qFormat/>'
                f'<w:pPr>{ppr_xml}</w:pPr><w:rPr>{rpr_xml}</w:rPr></w:style>')
    head_font = f'<w:rFonts w:ascii="Segoe UI Semibold" w:hAnsi="Segoe UI Semibold" w:cs="{CS_FONT}"/>'
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {NS}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{LATIN_FONT}" w:eastAsia="{LATIN_FONT}" w:hAnsi="{LATIN_FONT}" w:cs="{CS_FONT}"/>
<w:sz w:val="{body_sz}"/><w:szCs w:val="{body_cs}"/>{lang}</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>{'<w:pPr><w:bidi/></w:pPr>' if RTL else ''}<w:rPr><w:color w:val="1C2530"/></w:rPr></w:style>
<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/><w:semiHidden/></w:style>
{pstyle("Title", "Title", '<w:spacing w:before="240" w:after="240"/><w:pBdr><w:bottom w:val="single" w:sz="12" w:space="8" w:color="0E6B70"/></w:pBdr>', head_font + '<w:color w:val="0E3F44"/><w:sz w:val="52"/><w:szCs w:val="56"/>', extra='<w:uiPriority w:val="10"/>')}
{pstyle("Heading1", "heading 1", '<w:keepNext/><w:keepLines/><w:pageBreakBefore/><w:spacing w:before="0" w:after="200"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="4" w:color="9FC3C6"/></w:pBdr><w:outlineLvl w:val="0"/>', head_font + '<w:color w:val="0E5A5F"/><w:sz w:val="36"/><w:szCs w:val="40"/>', extra='<w:uiPriority w:val="9"/>')}
{pstyle("Heading2", "heading 2", '<w:keepNext/><w:keepLines/><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="1"/>', head_font + '<w:color w:val="0E5A5F"/><w:sz w:val="28"/><w:szCs w:val="32"/>', extra='<w:uiPriority w:val="9"/>')}
{pstyle("TOCHeading", "TOC Heading", '<w:keepNext/><w:spacing w:before="360" w:after="160"/>', head_font + '<w:color w:val="0E5A5F"/><w:sz w:val="32"/><w:szCs w:val="36"/>')}
{pstyle("TOC1", "toc 1", '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="' + str(AVAIL) + '"/></w:tabs><w:spacing w:before="60" w:after="40"/>', '<w:b/><w:bCs/>', extra='<w:uiPriority w:val="39"/>')}
{pstyle("TOC2", "toc 2", '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="' + str(AVAIL) + '"/></w:tabs><w:spacing w:after="20"/><w:ind w:left="360"/>', '<w:sz w:val="18"/><w:szCs w:val="22"/>', extra='<w:uiPriority w:val="39"/>')}
{pstyle("TableText", "Table Text", '<w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/>', '<w:sz w:val="16"/><w:szCs w:val="20"/>')}
{pstyle("AfterTable", "After Table", '<w:spacing w:before="0" w:after="80" w:line="120" w:lineRule="exact"/>', '<w:sz w:val="4"/><w:szCs w:val="4"/>')}
{pstyle("ListText", "List Text", '<w:spacing w:after="60"/><w:ind w:left="360" w:hanging="260"/>', '')}
{pstyle("Callout", "Callout", '<w:shd w:val="clear" w:color="auto" w:fill="EEF5F5"/><w:spacing w:before="0" w:after="0"/><w:ind w:left="240" w:right="240"/>', '<w:sz w:val="18"/><w:szCs w:val="22"/>')}
{pstyle("CalloutBullet", "Callout Bullet", '<w:shd w:val="clear" w:color="auto" w:fill="EEF5F5"/><w:spacing w:before="0" w:after="40"/><w:ind w:left="600" w:right="240" w:hanging="260"/>', '<w:sz w:val="18"/><w:szCs w:val="22"/>')}
{pstyle("CodeBlock", "Code Block", '<w:shd w:val="clear" w:color="auto" w:fill="F2F4F6"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="240" w:right="240"/>', f'<w:rFonts w:ascii="{CODE_FONT}" w:hAnsi="{CODE_FONT}" w:cs="{CODE_FONT}"/><w:sz w:val="16"/><w:szCs w:val="16"/>')}
<w:style w:type="character" w:styleId="CodeChar"><w:name w:val="Code Char"/><w:basedOn w:val="DefaultParagraphFont"/><w:qFormat/><w:rPr><w:rFonts w:ascii="{CODE_FONT}" w:hAnsi="{CODE_FONT}" w:cs="{CODE_FONT}"/><w:color w:val="1F3D5C"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:basedOn w:val="DefaultParagraphFont"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/><w:rPr><w:color w:val="0B5CAD"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:color w:val="6B7785"/><w:sz w:val="16"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:jc w:val="center"/></w:pPr><w:rPr><w:color w:val="6B7785"/><w:sz w:val="16"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/><w:semiHidden/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="table" w:styleId="DocTable"><w:name w:val="Doc Table"/><w:basedOn w:val="TableNormal"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="B9C7D0"/><w:left w:val="single" w:sz="4" w:space="0" w:color="B9C7D0"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="B9C7D0"/><w:right w:val="single" w:sz="4" w:space="0" w:color="B9C7D0"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="D5DEE4"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="D5DEE4"/></w:tblBorders><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>'''


def numbering():
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {NS}>
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/>
<w:pPr><w:ind w:left="360" w:hanging="260"/></w:pPr><w:rPr><w:rFonts w:ascii="Segoe UI" w:hAnsi="Segoe UI" w:cs="Segoe UI"/><w:color w:val="0E6B70"/></w:rPr></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>'''


def header_footer(kind):
    bidi = "<w:bidi/>" if RTL else ""
    rtl = "<w:rtl/>" if RTL else ""
    if kind == "header":
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}><w:p><w:pPr><w:pStyle w:val="Header"/>{bidi}</w:pPr>'
                f'<w:r><w:rPr>{rtl}</w:rPr><w:t xml:space="preserve">{x(T["header"].format(schema=SCHEMA))}</w:t></w:r></w:p></w:hdr>')
    def field(code):
        return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                f'<w:r><w:instrText xml:space="preserve"> {code} </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/>{bidi}</w:pPr>'
            f'<w:r><w:rPr>{rtl}</w:rPr><w:t xml:space="preserve">{x(T["page"])}</w:t></w:r>{field("PAGE")}'
            f'<w:r><w:rPr>{rtl}</w:rPr><w:t xml:space="preserve">{x(T["of"])}</w:t></w:r>{field("NUMPAGES")}</w:p></w:ftr>')


def main():
    lines = open(SRC, encoding="utf-8").read().split("\n")
    title, body = build_body(lines)
    sect = ('<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/><w:footerReference w:type="default" r:id="rIdFooter"/>'
            f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}" w:orient="landscape"/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" w:header="500" w:footer="500" w:gutter="0"/>'
            + ("<w:bidi/>" if RTL else "") + '<w:docGrid w:linePitch="360"/></w:sectPr>')
    drawing_ns = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
                  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                  'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS} {drawing_ns}><w:body>{body}{sect}</w:body></w:document>')
    settings = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings {NS}><w:defaultTabStop w:val="720"/>'
                '<w:characterSpacingControl w:val="doNotCompress"/>'
                '<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
                + ('<w:themeFontLang w:val="en-US" w:bidi="fa-IR"/>' if RTL else '<w:themeFontLang w:val="en-US"/>')
                + "</w:settings>")
    fonts = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:fonts {NS}>'
             '<w:font w:name="Segoe UI"><w:charset w:val="00"/><w:family w:val="swiss"/><w:pitch w:val="variable"/></w:font>'
             '<w:font w:name="Segoe UI Semibold"><w:charset w:val="00"/><w:family w:val="swiss"/><w:pitch w:val="variable"/></w:font>'
             '<w:font w:name="Consolas"><w:charset w:val="00"/><w:family w:val="modern"/><w:pitch w:val="fixed"/></w:font>'
             + ('<w:font w:name="B Nazanin"><w:altName w:val="Tahoma"/><w:charset w:val="B2"/><w:family w:val="auto"/><w:pitch w:val="variable"/></w:font>'
                '<w:font w:name="Tahoma"><w:charset w:val="B2"/><w:family w:val="swiss"/><w:pitch w:val="variable"/></w:font>' if RTL else "")
             + "</w:fonts>")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{x(title or "")}</dc:title><dc:language>{"fa-IR" if RTL else "en-US"}</dc:language>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            '</cp:coreProperties>')
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           '<Application>oradoc md2docx</Application></Properties>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                     '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
                     '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
                     '<Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>'
                     '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                     '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                     '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                     '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '<Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
                '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
                '<Relationship Id="rIdFonts" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>'
                '<Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
                '<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
                + ('<Relationship Id="rIdImg1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/erd_relationships.png"/>' if IMG else "")
                + '</Relationships>')
    if IMG:
        content_types = content_types.replace('<Default Extension="xml"', '<Default Extension="png" ContentType="image/png"/><Default Extension="xml"')
    with zipfile.ZipFile(OUT, "x", zipfile.ZIP_DEFLATED) as z:  # "x": never overwrite
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles())
        z.writestr("word/numbering.xml", numbering())
        z.writestr("word/settings.xml", settings)
        z.writestr("word/fontTable.xml", fonts)
        z.writestr("word/header1.xml", header_footer("header"))
        z.writestr("word/footer1.xml", header_footer("footer"))
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        if IMG:
            z.write(IMG, "word/media/erd_relationships.png")
    print(f"{OUT}: title={title!r} tables={body.count('<w:tbl>')} paragraphs={body.count('<w:p>')}")


def convert(src, out, lang, schema, img=None, header=None):
    """Write <out> (never overwrites) from oradoc Markdown <src>; <img> replaces the ```mermaid block;
    <header> (with {schema}) replaces the default page header text."""
    global SRC, OUT, LANG, SCHEMA, IMG, RTL, CS_FONT, T
    SRC, OUT, LANG, SCHEMA, IMG = str(src), str(out), lang, schema, (str(img) if img else None)
    RTL = lang == "fa"
    CS_FONT = "B Nazanin" if RTL else "Segoe UI"
    T = dict(TEXTS[lang], **({"header": header} if header else {}))
    main()


if __name__ == "__main__":
    # Usage: python md2docx.py <input.md> <output.docx> <fa|en> <SCHEMA> [relationships.png]
    sys.stdout.reconfigure(encoding="utf-8")
    convert(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)

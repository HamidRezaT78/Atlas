"""Render a Mermaid .mmd fully offline: the vendored mermaid.min.js in headless Chrome with all host
resolution blocked. Returns the rendered node boxes (used for the draw.io layout) and optionally a PNG.

Usage: python render_erd.py <diagram.mmd> <work_dir> [png_scale]   (or render() from publish.py)
"""
import base64
import html as htmlmod
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MERMAID_JS = Path(__file__).resolve().parents[1] / "vendor" / "mermaid-11.17.2" / "mermaid.min.js"
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser():
    for c in CHROME_CANDIDATES:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError("Chrome/Edge not found: " + ", ".join(CHROME_CANDIDATES))


def page(text, scale):
    payload = json.dumps(text).replace("</", "<\\/")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>erd</title>
<style>html,body{{margin:0;padding:0;background:#ffffff}} #out{{display:inline-block;padding:24px}}</style>
<script src="mermaid.min.js"></script></head>
<body><div id="out"></div><pre id="result" style="display:none"></pre>
<script>
const source = {payload};
const SCALE = {scale};
mermaid.initialize({{ startOnLoad: false, securityLevel: "strict", theme: "default", maxTextSize: 500000,
  maxEdges: 2000, fontFamily: "Segoe UI, Arial, sans-serif", htmlLabels: false,
  flowchart: {{ htmlLabels: false }}, er: {{ useMaxWidth: false }} }});
function exportPng(el) {{
  return new Promise((resolve, reject) => {{
    const vb = el.viewBox.baseVal;
    const w = Math.ceil(vb.width), h = Math.ceil(vb.height);
    const xml = new XMLSerializer().serializeToString(el);
    const img = new Image();
    img.onload = () => {{
      const c = document.createElement("canvas");
      c.width = Math.round(w * SCALE); c.height = Math.round(h * SCALE);
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      try {{ resolve({{ png: c.toDataURL("image/png"), pngWidth: c.width, pngHeight: c.height }}); }} catch (e) {{ reject(e); }}
    }};
    img.onerror = () => reject(new Error("svg image load failed"));
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  }});
}}
mermaid.render("erd", source).then(async ({{ svg }}) => {{
  const out = document.getElementById("out");
  out.innerHTML = svg;
  const el = out.querySelector("svg");
  const vb = el.viewBox.baseVal;
  el.setAttribute("width", Math.ceil(vb.width));
  el.setAttribute("height", Math.ceil(vb.height));
  el.style.maxWidth = "none";
  const rect = out.getBoundingClientRect();
  const labels = Array.from(el.querySelectorAll("text, .label, foreignObject")).map(n => n.textContent.trim());
  const res = {{
    ok: true, width: Math.ceil(rect.width), height: Math.ceil(rect.height),
    viewBox: [vb.width, vb.height],
    entityGroups: el.querySelectorAll('g[id*="entity-"]').length,
    entityNodes: el.querySelectorAll('g.node').length,
    relationshipPaths: el.querySelectorAll('path.relationshipLine, .relationshipLine path, path[class*="relationship"]').length,
    edgePaths: el.querySelectorAll('g.edgePaths path, path.edge-pattern-solid, path.edge-pattern-dashed').length,
    relationshipLabels: el.querySelectorAll('.relationshipLabel, g.edgeLabel').length,
    labels: labels,
    foreignObjects: el.querySelectorAll("foreignObject").length,
    nodes: Array.from(el.querySelectorAll("g.node")).map(n => {{
      const sr = el.getBoundingClientRect(), r = n.getBoundingClientRect();
      return {{ x: r.left - sr.left, y: r.top - sr.top, w: r.width, h: r.height,
               texts: Array.from(n.querySelectorAll("text")).map(t => t.textContent.trim()) }};
    }})
  }};
  if (SCALE > 0) {{
    try {{ Object.assign(res, await exportPng(el)); }} catch (e) {{ res.pngError = String(e); }}
  }}
  document.getElementById("result").textContent = JSON.stringify(res);
  document.title = "done";
}}).catch(e => {{ document.getElementById("result").textContent = JSON.stringify({{ ok: false, error: String(e) }}); document.title = "error"; }});
</script></body></html>"""


def render(mmd_path, work_dir, scale=0.0, name="erd"):
    """Render <mmd_path> in <work_dir>/<name>/; returns the result dict (nodes, counts, png bytes if scale>0)."""
    work = Path(work_dir) / name
    work.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(MERMAID_JS, work / "mermaid.min.js")
    html_path = work / "erd.html"
    html_path.write_text(page(Path(mmd_path).read_text(encoding="utf-8"), scale), encoding="utf-8")
    cmd = [find_browser(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           f"--user-data-dir={work / 'profile'}", "--host-resolver-rules=MAP * ~NOTFOUND",
           "--allow-file-access-from-files", "--window-size=1600,1200", "--virtual-time-budget=120000",
           "--dump-dom", html_path.resolve().as_uri()]
    dom = subprocess.run(cmd, capture_output=True, timeout=600).stdout.decode("utf-8", "replace")
    m = re.search(r'<pre id="result"[^>]*>(.*?)</pre>', dom, re.S)
    if not m or not m.group(1).strip():
        raise RuntimeError(f"Mermaid render produced no result for {mmd_path}")
    res = json.loads(htmlmod.unescape(m.group(1)))
    if not res.get("ok"):
        raise RuntimeError(f"Mermaid render failed for {mmd_path}: {res.get('error')}")
    if scale > 0:
        if not res.get("png"):
            raise RuntimeError(f"PNG export failed for {mmd_path}: {res.get('pngError')}")
        res["png_bytes"] = base64.b64decode(res.pop("png").split(",", 1)[1])
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = render(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.0)
    out = Path(sys.argv[2]) / "erd"
    if "png_bytes" in r:
        (out / "erd.png").write_bytes(r.pop("png_bytes"))
    (out / "nodes.json").write_text(json.dumps(r["nodes"]), encoding="utf-8")
    print(f"entities={r['entityNodes']} relationshipLabels={r['relationshipLabels']} svg={r['viewBox']}")

"""Self-contained HTML viewer: the same diagram, with draggable devices.

Open the file in any browser (no server, no internet). Drag a device and its
links and port labels follow; links stay orthogonal. "Download SVG" saves the
current arrangement. The CSV stays the source of truth: moves are not written
back.
"""
import json

from . import style
from .text import FONT_STACK, line_height


def _lines(lines):
    return [{"t": l.text, "s": l.size, "b": l.bold, "c": l.color, "h": line_height(l.size)} for l in lines]


def _r(r):
    return [round(r.x, 2), round(r.y, 2), round(r.w, 2), round(r.h, 2)]


def scene_json(scene):
    nodes = {n.id: n for n in scene.nodes}
    data = {"w": scene.width, "h": scene.height, "nodes": [], "edges": [], "labels": [], "groups": []}
    for n in scene.nodes:
        data["nodes"].append({"id": n.id, "r": _r(n.rect), "icon": style.icon_svg(n.icon, n.color, 0, 0, 32),
                              "color": n.color, "lines": _lines(n.lines)})
    label_node = {}
    for e in scene.edges:
        p0, p1 = e.points[0], e.points[-1]
        data["edges"].append({"id": e.id, "pts": [[round(x, 2), round(y, 2)] for x, y in e.points],
                              "s": e.source, "t": e.target, "peer": e.kind == "peer"})
        for lid in e.labels:
            lab = next(l for l in scene.labels if l.id == lid)
            d0 = abs(lab.rect.cx - p0[0]) + abs(lab.rect.cy - p0[1])
            d1 = abs(lab.rect.cx - p1[0]) + abs(lab.rect.cy - p1[1])
            label_node[lid] = e.source if d0 <= d1 else e.target
    for l in scene.labels:
        data["labels"].append({"id": l.id, "r": _r(l.rect), "lines": _lines(l.lines), "kind": l.kind,
                               "bg": l.background, "tab": l.tab, "node": label_node.get(l.id)})
    for g in scene.groups:
        data["groups"].append({"id": g.id, "r": _r(g.rect), "color": g.color, "label": g.label,
                               "members": [m for m in g.members if m in nodes]})
    return data


TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
body{margin:0;font-family:__FONT__;background:#f1f5f9}
#bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #e2e8f0;padding:8px 14px;font-size:13px;color:#334155;z-index:2}
#bar button{margin-left:10px;padding:4px 10px;border:1px solid #cbd5e1;background:#f8fafc;border-radius:6px;cursor:pointer}
#wrap{padding:16px}
svg{user-select:none;-webkit-user-select:none;background:#fff;box-shadow:0 1px 3px rgba(15,23,42,.12);border-radius:6px}
.node{cursor:grab}.node.drag{cursor:grabbing}
</style></head><body>
<div id="bar"><b>__TITLE__</b> &nbsp;Drag devices to rearrange. Changes stay in this page only.
<button id="reset">Reset layout</button><button id="dl">Download SVG</button></div>
<div id="wrap"><svg id="d" xmlns="http://www.w3.org/2000/svg"></svg></div>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg", svg = document.getElementById("d");
svg.setAttribute("width", D.w); svg.setAttribute("height", D.h);
svg.setAttribute("viewBox", `0 0 ${D.w} ${D.h}`); svg.setAttribute("font-family", "__FONT__");
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
const text = (g, x, y, lines, tab) => { let cy = y; for (const l of lines) {
  const parts = tab ? l.t.split("\t") : [l.t];
  parts.forEach((p, i) => { const t = el("text", {x: x + i * (tab || 0), y: cy + l.h * 0.78, "font-size": l.s,
    fill: l.c, "font-weight": l.b ? "bold" : "normal"}, g); t.textContent = p; }); cy += l.h; } };
let off = {};
const L = {groups: el("g", {}, svg), edges: el("g", {}, svg), nodes: el("g", {}, svg), labels: el("g", {}, svg)};
function pos(id) { return off[id] || [0, 0]; }
function draw() {
  for (const k in L) L[k].innerHTML = "";
  const nodeR = {}; for (const n of D.nodes) { const [dx, dy] = pos(n.id); nodeR[n.id] = [n.r[0] + dx, n.r[1] + dy, n.r[2], n.r[3]]; }
  const labR = {};
  for (const lb of D.labels) { const [dx, dy] = lb.node ? pos(lb.node) : [0, 0]; labR[lb.id] = [lb.r[0] + dx, lb.r[1] + dy, lb.r[2], lb.r[3]]; }
  for (const g of D.groups) {
    let r = g.r;
    if (g.members.some(m => off[m])) {
      const rs = g.members.map(m => nodeR[m]); const pad = 12, lab = labR[g.label];
      const x0 = Math.min(...rs.map(r => r[0])) - pad, y0 = Math.min(...rs.map(r => r[1])) - pad;
      const x1 = Math.max(Math.max(...rs.map(r => r[0] + r[2])) + pad, x0 + lab[2] + 2 * pad);
      const y1 = Math.max(...rs.map(r => r[1] + r[3])) + pad + lab[3] + 4;
      r = [x0, y0, x1 - x0, y1 - y0]; labR[g.label] = [x0 + pad, y1 - 4 - lab[3], lab[2], lab[3]];
    }
    el("rect", {x: r[0], y: r[1], width: r[2], height: r[3], rx: 10, fill: g.color, "fill-opacity": .05,
      stroke: g.color, "stroke-opacity": .7, "stroke-width": 1.2, "stroke-dasharray": "6 4"}, L.groups);
  }
  for (const e of D.edges) {
    let p = e.pts.map(q => q.slice()); const [sx, sy] = pos(e.s), [tx, ty] = pos(e.t);
    if (sx || sy || tx || ty) {
      const a = [p[0][0] + sx, p[0][1] + sy], b = [p[p.length - 1][0] + tx, p[p.length - 1][1] + ty];
      if (e.peer && p.length === 2) {
        p = Math.abs(a[1] - b[1]) < 0.5 ? [a, b] : [a, [(a[0] + b[0]) / 2, a[1]], [(a[0] + b[0]) / 2, b[1]], b];
      } else if (p.length === 2) {
        const my = (a[1] + b[1]) / 2; p = [a, [a[0], my], [b[0], my], b];
      } else {
        p[0] = a; p[1] = [a[0], p[1][1]]; p[p.length - 1] = b; p[p.length - 2] = [b[0], p[p.length - 2][1]];
      }
    }
    el("polyline", {points: p.map(q => q.join(",")).join(" "), fill: "none", stroke: e.peer ? "#dc2626" : "#334155",
      "stroke-width": 1.6, "stroke-dasharray": e.peer ? "5 3" : "none", "stroke-linejoin": "round"}, L.edges);
  }
  for (const n of D.nodes) {
    const [x, y, w, h] = nodeR[n.id];
    const g = el("g", {class: "node", "data-id": n.id}, L.nodes);
    el("rect", {x: x + 1, y: y + 2, width: w, height: h, rx: 8, fill: "#0f172a", "fill-opacity": .07}, g);
    el("rect", {x, y, width: w, height: h, rx: 8, fill: "#fff", stroke: "#cbd5e1"}, g);
    el("rect", {x, y: y + 6, width: 3, height: h - 12, rx: 1.5, fill: n.color}, g);
    const ic = el("g", {transform: `translate(${x + 10},${y + h / 2 - 16})`}, g); ic.innerHTML = n.icon;
    const th = n.lines.reduce((s, l) => s + l.h, 0); text(g, x + 52, y + h / 2 - th / 2, n.lines);
  }
  for (const lb of D.labels) {
    const [x, y, w, h] = labR[lb.id];
    if (lb.kind === "legend") { el("rect", {x, y, width: w, height: h, rx: 8, fill: "#f8fafc", stroke: "#e2e8f0"}, L.labels);
      text(L.labels, x + 8, y + 6, lb.lines, lb.tab); continue; }
    if (lb.bg) el("rect", {x, y, width: w, height: h, rx: 2, fill: "#fff", "fill-opacity": .92}, L.labels);
    text(L.labels, x + 3, y + 2, lb.lines);
  }
}
let drag = null;
svg.addEventListener("pointerdown", ev => { const g = ev.target.closest(".node"); if (!g) return; ev.preventDefault();
  const id = g.dataset.id, pt = svgPt(ev); drag = {id, start: pt, base: pos(id).slice()}; g.classList.add("drag");
  svg.setPointerCapture(ev.pointerId); });
svg.addEventListener("pointermove", ev => { if (!drag) return; const pt = svgPt(ev);
  off[drag.id] = [Math.round(drag.base[0] + pt[0] - drag.start[0]), Math.round(drag.base[1] + pt[1] - drag.start[1])]; draw(); });
svg.addEventListener("pointerup", () => { drag = null; });
function svgPt(ev) { const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY; const q = p.matrixTransform(svg.getScreenCTM().inverse()); return [q.x, q.y]; }
document.getElementById("reset").onclick = () => { off = {}; draw(); };
document.getElementById("dl").onclick = () => { const blob = new Blob([new XMLSerializer().serializeToString(svg)], {type: "image/svg+xml"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "__TITLE__.svg"; a.click(); };
draw();
</script></body></html>
"""


def render_html(scene, title="Network") -> str:
    data = json.dumps(scene_json(scene)).replace("</", "<\\/")
    safe = title.replace("<", "").replace(">", "").replace('"', "")
    return (TEMPLATE.replace("__DATA__", data).replace("__TITLE__", safe)
            .replace("__FONT__", FONT_STACK))

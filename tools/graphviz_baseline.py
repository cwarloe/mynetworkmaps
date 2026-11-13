"""Graphviz baseline: draw the same CSV with plain Graphviz `dot` and run the
same overlap checker on Graphviz's own output geometry.

Needs Graphviz installed and `dot` on PATH (Windows: `winget install graphviz`).
Usage:  python tools/graphviz_baseline.py samples/redundant_network.csv -o out/graphviz
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netdiag import style  # noqa: E402
from netdiag.geometry import check, is_clean, summary  # noqa: E402
from netdiag.model import TIERS, load_csv  # noqa: E402
from netdiag.scene import Edge, Group, Label, Node, Rect, Scene  # noqa: E402
from netdiag.validate import has_errors, validate  # noqa: E402


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def end_label(end):
    parts = [p for p in (end.port, end.address or (f"VLAN {end.vlan}" if end.vlan else "")) if p]
    return "\\n".join(parts)


def to_dot(topo, splines="true", title="", clusters=False):
    link_rows = {id(e.row) for l in topo.links for e in (l.a, l.b) if e.row is not None}
    o = ["graph G {",
         f'  graph [rankdir=TB, splines={splines}, nodesep=0.5, ranksep=0.9, fontname="Helvetica", '
         f'fontsize=11, labelloc=t, label={q(title)}];',
         '  node [shape=box, style="rounded,filled", fillcolor="#ffffff", color="#94a3b8", '
         'fontname="Helvetica", fontsize=10];',
         '  edge [fontname="Helvetica", fontsize=8, color="#334155", labelfontsize=8];']
    by_tier = {t: [] for t in TIERS}
    for d in topo.devices.values():
        by_tier[d.tier].append(d)
    for d in topo.devices.values():
        extra = [f"{r.interface} {r.address}".strip() for r in d.rows if r.address and id(r) not in link_rows]
        label = "\\n".join([d.name, style.caption(d.icon, d.tier)] + extra)
        o.append(f"  {q(d.name)} [label={q(label).replace(chr(92) * 2 + 'n', chr(92) + 'n')}, "
                 f'color="{style.icon_color(d.icon, d.tier)}", penwidth=1.4];')
    for t in TIERS:
        if not by_tier[t] or (t == "endpoint" and clusters):
            continue
        o.append("  { rank=same; " + " ".join(q(d.name) for d in by_tier[t]) + " }")
    groups = {}
    for d in by_tier["endpoint"] if clusters else []:
        groups.setdefault(topo.device_vlan(d), []).append(d)
    for i, (vid, devs) in enumerate(groups.items()):
        if not vid:
            continue
        v = topo.vlans.get(vid)
        lab = f"VLAN {vid} · {v.name} · {v.subnet}" if v else f"VLAN {vid}"
        o.append(f"  subgraph cluster_{i} {{ label={q(lab)}; style=dashed; color=\"#64748b\"; "
                 + " ".join(q(d.name) + ";" for d in devs) + " }")
    for l in topo.links:
        ta, tb = TIERS.index(topo.devices[l.a.device].tier), TIERS.index(topo.devices[l.b.device].tier)
        same = ta == tb
        a, b = (l.a, l.b) if ta <= tb else (l.b, l.a)   # tail is the upper device, so dot ranks it higher
        attrs = [f"taillabel={q(end_label(a))}", f"headlabel={q(end_label(b))}", f'id="{l.id}"']
        if same:
            attrs += ["constraint=false", 'style=dashed', 'color="#dc2626"']
        o.append(f"  {q(a.device)} -- {q(b.device)} [{', '.join(attrs)}];".replace("\\\\n", "\\n"))
    o.append("}")
    return "\n".join(o)


def _bezier(pts, steps=10):
    out = [tuple(pts[0])]
    for i in range(0, len(pts) - 3, 3):
        p0, p1, p2, p3 = pts[i:i + 4]
        for s in range(1, steps + 1):
            t = s / steps
            mt = 1 - t
            x = mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0]
            y = mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]
            out.append((x, y))
    return out


def _text_rect(ops, flip):
    size, rects = 14.0, []
    for op in ops or []:
        if op["op"] == "F":
            size = float(op["size"])
        elif op["op"] == "T":
            x, y = op["pt"]
            w = float(op["width"])
            x0 = {"c": x - w / 2, "l": x, "r": x - w}[op["align"]]
            top = flip(y) - size * 0.9
            rects.append(Rect(x0, top, w, size * 1.2))
    if not rects:
        return None
    x0, y0 = min(r.x for r in rects), min(r.y for r in rects)
    return Rect(x0, y0, max(r.x2 for r in rects) - x0, max(r.y2 for r in rects) - y0)


def scene_from_json(data):
    bb = [float(v) for v in data["bb"].split(",")]
    H = bb[3]
    flip = lambda y: H - y
    nodes, labels, edges, groups = [], [], [], []
    objs = data.get("objects", [])
    names = {}
    for ob in objs:
        if "nodes" in ob or "subgraphs" in ob:   # subgraph / cluster
            if ob.get("name", "").startswith("cluster") and "bb" in ob:
                x0, y0, x1, y1 = [float(v) for v in ob["bb"].split(",")]
                r = _text_rect(ob.get("_ldraw_"), flip)
                lid = f"grp_lbl_{ob['name']}"
                if r:
                    labels.append(Label(id=lid, rect=r, lines=["x"], kind="group"))
                groups.append(Group(id=ob["name"], rect=Rect(x0, flip(y1), x1 - x0, y1 - y0), label=lid))
            continue
        if "pos" not in ob:
            continue
        x, y = [float(v) for v in ob["pos"].split(",")]
        w, h = float(ob["width"]) * 72, float(ob["height"]) * 72
        names[ob["_gvid"]] = ob["name"]
        nodes.append(Node(id=ob["name"], rect=Rect(x - w / 2, flip(y) - h / 2, w, h), icon="", color="",
                          lines=[]))
    r = _text_rect(data.get("_ldraw_"), flip)
    if r:
        labels.append(Label(id="title", rect=r, lines=["x"], kind="title"))
    for i, e in enumerate(data.get("edges", [])):
        eid = e.get("id", f"e{i}")
        pts = []
        for op in e.get("_draw_", []):
            if op["op"] in ("b", "B"):
                pts += [(px, flip(py)) for px, py in _bezier(op["points"])]
        lids = []
        for key in ("_tldraw_", "_hldraw_", "_ldraw_"):
            r = _text_rect(e.get(key), flip)
            if r:
                lid = f"{eid}{key}"
                labels.append(Label(id=lid, rect=r, lines=["x"], kind="port", owner=eid))
                lids.append(lid)
        edges.append(Edge(id=eid, points=pts, source=names.get(e["tail"], ""), target=names.get(e["head"], ""),
                          labels=lids))
    return Scene(bb[2], bb[3], nodes, edges, labels, groups)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("-o", "--out", default="out/graphviz")
    ap.add_argument("--splines", default="true,ortho", help="comma list of Graphviz splines modes")
    ap.add_argument("--clusters", action="store_true",
                    help="draw VLAN clusters (Graphviz then ignores the endpoint row; off by default)")
    args = ap.parse_args(argv)
    dot = shutil.which("dot")
    if not dot:
        print("Graphviz 'dot' not found on PATH. On Windows: winget install graphviz", file=sys.stderr)
        return 2
    topo = load_csv(args.csv)
    if has_errors(validate(topo)):
        print("CSV has validation errors; run netdiag first.", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.csv).stem
    results = {}
    for mode in args.splines.split(","):
        base = out / f"{stem}.graphviz-{'spline' if mode == 'true' else mode}"
        dot_src = to_dot(topo, mode, stem, args.clusters)
        f = lambda ext: Path(f"{base}.{ext}")
        f("dot").write_text(dot_src, encoding="utf-8")
        for fmt in ("json", "svg", "png"):
            subprocess.run([dot, f"-T{fmt}", "-o", str(f(fmt)), str(f("dot"))], check=True, capture_output=True)
        data = json.loads(f("json").read_text(encoding="utf-8"))
        res = check(scene_from_json(data))
        results[base.name] = summary(res)
        print(f"{base.name}: " + ", ".join(f"{k}={v}" for k, v in summary(res).items())
              + ("  (clean)" if is_clean(res) else ""))
    (out / f"{stem}.graphviz-overlaps.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

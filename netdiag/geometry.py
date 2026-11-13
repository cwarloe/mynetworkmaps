"""Overlap checker. Works on any scene (ours, or one rebuilt from Graphviz
JSON) and counts the things that make a diagram look muddled."""
from __future__ import annotations

import itertools

TOL = 0.5


def _seg_hits_rect(p, q, r, tol=TOL):
    """True if segment p-q passes through the interior of rect r (Liang-Barsky)."""
    x0, y0 = p
    x1, y1 = q
    xmin, ymin, xmax, ymax = r.x + tol, r.y + tol, r.x2 - tol, r.y2 - tol
    if xmin >= xmax or ymin >= ymax:
        return False
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if pk == 0:
            if qk < 0:
                return False
        else:
            t = qk / pk
            if pk < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return t1 - t0 > 1e-9


def _segments(edge):
    return list(zip(edge.points, edge.points[1:]))


def _cross(a, b, c, d):
    """Proper crossing of segments a-b and c-d (shared endpoints do not count)."""
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-6 else (1 if v > 0 else -1)
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def _collinear_overlap(a, b, c, d, tol=1.0):
    """Two axis-aligned segments lying on top of each other for more than tol."""
    if abs(a[0] - b[0]) < 0.01 and abs(c[0] - d[0]) < 0.01 and abs(a[0] - c[0]) < tol:
        lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
        return hi - lo > tol
    if abs(a[1] - b[1]) < 0.01 and abs(c[1] - d[1]) < 0.01 and abs(a[1] - c[1]) < tol:
        lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
        return hi - lo > tol
    return False


def check(scene) -> dict:
    labels = [l for l in scene.labels if l.lines]
    res = {"label_label": [], "label_node": [], "edge_node": [], "label_edge": [],
           "label_own_edge": [], "node_node": [], "edge_overlap": [], "edge_crossings": 0}
    for a, b in itertools.combinations(labels, 2):
        if a.rect.intersects(b.rect):
            res["label_label"].append((a.id, b.id))
    for a, b in itertools.combinations(scene.nodes, 2):
        if a.rect.intersects(b.rect):
            res["node_node"].append((a.id, b.id))
    for l in labels:
        for n in scene.nodes:
            if l.rect.intersects(n.rect):
                res["label_node"].append((l.id, n.id))
    for e in scene.edges:
        segs = _segments(e)
        for n in scene.nodes:
            if any(_seg_hits_rect(p, q, n.rect, tol=1.5) for p, q in segs):
                res["edge_node"].append((e.id, n.id))
        for l in labels:
            if any(_seg_hits_rect(p, q, l.rect) for p, q in segs):
                # a line striking through its own port label is just as unreadable
                res["label_own_edge" if l.owner == e.id else "label_edge"].append((l.id, e.id))
    for e1, e2 in itertools.combinations(scene.edges, 2):
        s1, s2 = _segments(e1), _segments(e2)
        for (a, b), (c, d) in itertools.product(s1, s2):
            if _cross(a, b, c, d):
                res["edge_crossings"] += 1
            elif _collinear_overlap(a, b, c, d):
                res["edge_overlap"].append((e1.id, e2.id))
    return res


def summary(res) -> dict:
    return {k: (v if isinstance(v, int) else len(v)) for k, v in res.items()}


def is_clean(res) -> bool:
    s = summary(res)
    return all(s[k] == 0 for k in ("label_label", "label_node", "edge_node", "node_node",
                                   "label_edge", "label_own_edge", "edge_overlap"))

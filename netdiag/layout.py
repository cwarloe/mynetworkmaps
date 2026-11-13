"""Deterministic layered layout.

Devices sit in fixed role rows (edge, firewall, core, distribution, access,
endpoints). Links are orthogonal: down from a port on the upper device, across
on a dedicated horizontal track in the channel between rows, and down into a
port on the lower device. Port labels (interface and IP) sit beside their own
vertical segment inside reserved label zones, and node widths and gaps are
computed from measured label sizes, so labels cannot collide by construction.
The overlap checker in geometry.py verifies that on the final output anyway.
"""
from __future__ import annotations

import ipaddress
import itertools
from collections import defaultdict
from dataclasses import dataclass, field

from . import style
from .model import TIERS, TIER_TITLES, Topology, parse_cidr
from .scene import Edge, Group, Label, Node, Rect, Scene, TextLine
from .text import block_size

MARGIN = 32
GUTTER = 104          # left column with row titles
NODE_GAP = 30
DUMMY_W = 6
PAD = 10
ICON = 32
SLOT_PAD = 12
LBL_GAP = 6
LPAD_X, LPAD_Y = 3, 2
TRACK = 12
ZONE_GAP = 6
GPAD = 12
GROUP_GAP = 22
PORT_FONT = 10
NAME_FONT = 12.5
SUB_FONT = 10


# ----------------------------------------------------------------------------
@dataclass
class Port:
    item: str
    side: str                 # top | bottom | left | right
    edge: str
    other: str = ""          # item at the other end of this hop (for ordering)
    lines: list = field(default_factory=list)
    lw: float = 0.0           # label box size
    lh: float = 0.0
    x: float = 0.0
    y: float = 0.0


@dataclass
class Item:
    id: str
    tier: int
    dev: object = None        # Device or None for dummies
    w: float = 0.0
    h: float = 0.0
    x: float = 0.0            # center x
    y: float = 0.0            # top y
    lines: list = field(default_factory=list)
    block: str = ""
    ports: list = field(default_factory=list)

    @property
    def dummy(self):
        return self.dev is None


@dataclass
class Hop:
    edge: str
    upper: str
    lower: str
    up_port: Port = None
    low_port: Port = None
    track: int = -1


def _label_lines(end):
    lines = []
    if end.port:
        lines.append(TextLine(end.port, PORT_FONT, False, style.INK))
    if end.address:
        lines.append(TextLine(end.address, PORT_FONT, False, style.ADDR))
    elif end.vlan:
        lines.append(TextLine(f"VLAN {end.vlan}", PORT_FONT, False, style.MUTED))
    return lines


def _label_box(lines):
    w, h = block_size([(l.text, l.size, l.bold) for l in lines])
    if not lines:
        return 0.0, 0.0
    return w + 2 * LPAD_X, h + 2 * LPAD_Y


def _node_lines(dev, link_rows):
    lines = [TextLine(dev.name, NAME_FONT, True, style.INK),
             TextLine(style.caption(dev.icon, dev.tier), SUB_FONT, False, style.MUTED)]
    for r in dev.rows:
        if r.address and id(r) not in link_rows:
            prefix = f"{r.interface} " if r.interface else ""
            lines.append(TextLine(f"{prefix}{r.address}", SUB_FONT, False, style.ADDR))
    return lines


def _node_size(lines):
    tw, th = block_size([(l.text, l.size, l.bold) for l in lines])
    return PAD + ICON + PAD + tw + PAD + 2, max(ICON + 2 * PAD, th + 2 * PAD)


def _pava(desired, weights, seps):
    """Positions x_i (in order) minimizing sum w(x-d)^2 with x_{i+1}-x_i >= sep_i."""
    n = len(desired)
    off = [0.0] * n
    for i in range(1, n):
        off[i] = off[i - 1] + seps[i - 1]
    target = [desired[i] - off[i] for i in range(n)]
    blocks = []  # [value, weight, count]
    for i in range(n):
        blocks.append([target[i], weights[i], 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            wt = w1 + w2
            blocks.append([(v1 * w1 + v2 * w2) / wt, wt, c1 + c2])
    out, i = [], 0
    for v, _, c in blocks:
        for _ in range(c):
            out.append(v + off[i])
            i += 1
    return out


def _vlan_title(topo, vid):
    v = topo.vlans.get(vid)
    if v is None:
        return f"VLAN {vid}"
    return f"VLAN {vid} · {v.name} · {v.subnet}"


# ----------------------------------------------------------------------------
def layout(topo: Topology, title: str = "") -> Scene:
    if not topo.has_links:
        return layout_inventory(topo, title)
    links = [l for l in topo.links if l.b.device in topo.devices and l.a.device != l.b.device]
    present = [t for t in TIERS if any(d.tier == t for d in topo.devices.values())]
    tidx = {t: i for i, t in enumerate(present)}
    link_rows = set()
    for l in links:
        for e in (l.a, l.b):
            if e.row is not None:
                link_rows.add(id(e.row))

    items: dict[str, Item] = {}
    order: list[list[str]] = [[] for _ in present]
    for name, dev in topo.devices.items():
        it = Item(id=name, tier=tidx[dev.tier], dev=dev)
        it.lines = _node_lines(dev, link_rows)
        it.w, it.h = _node_size(it.lines)
        items[name] = it
        order[it.tier].append(name)

    hops: list[Hop] = []
    same: list = []          # (link, left_end, right_end)  same-row links
    edge_ends = {}           # edge id -> (top end, bottom end) LinkEnds
    for l in links:
        ta, tb = items[l.a.device].tier, items[l.b.device].tier
        if ta == tb:
            same.append(l)
            continue
        top, bot = (l.a, l.b) if ta < tb else (l.b, l.a)
        edge_ends[l.id] = (top, bot)
        t0, t1 = items[top.device].tier, items[bot.device].tier
        chain = [top.device]
        for t in range(t0 + 1, t1):
            did = f"_d_{l.id}_{t}"
            items[did] = Item(id=did, tier=t, w=DUMMY_W, h=0)
            order[t].append(did)
            chain.append(did)
        chain.append(bot.device)
        for u, d in zip(chain, chain[1:]):
            hops.append(Hop(edge=l.id, upper=u, lower=d))

    # ---- blocks (things that must stay together in a row) -------------------
    endpoint_tier = tidx.get("endpoint")
    parent = {}

    def find(a):
        while parent.get(a, a) != a:
            a = parent[a]
        return a
    for l in same:
        parent[find(l.a.device)] = find(l.b.device)
    vlan_of = {}
    for iid, it in items.items():
        if it.dummy:
            it.block = iid
        elif it.tier == endpoint_tier:
            vid = topo.device_vlan(it.dev)
            vlan_of[iid] = vid
            it.block = f"vlan:{vid}" if vid else iid
        else:
            it.block = f"comp:{find(iid)}"

    up = defaultdict(list)
    down = defaultdict(list)
    for h in hops:
        down[h.upper].append(h.lower)
        up[h.lower].append(h.upper)
    same_adj = defaultdict(list)
    for l in same:
        same_adj[l.a.device].append(l.b.device)
        same_adj[l.b.device].append(l.a.device)

    def comp_path(members):
        # BFS from the first member so chained devices sit side by side
        start, seen, out = members[0], set(), []
        stack = [start]
        while stack:
            n = stack.pop(0)
            if n in seen:
                continue
            seen.add(n)
            out.append(n)
            stack.extend(sorted((m for m in same_adj[n] if m not in seen), key=members.index))
        return out + [m for m in members if m not in seen]

    def regroup(t, keyf):
        row = order[t]
        pos = {n: i for i, n in enumerate(row)}
        blocks = defaultdict(list)
        for n in row:
            blocks[items[n].block].append(n)
        scored = []
        for b, mem in blocks.items():
            vals = [keyf(n) for n in mem]
            known = [v for v in vals if v is not None]
            bary = sum(known) / len(known) if known else sum(pos[n] for n in mem) / len(mem)
            if b.startswith("comp:"):
                mem = comp_path(mem)
                if len(mem) > 1:
                    f, l_ = keyf(mem[0]), keyf(mem[-1])
                    if f is not None and l_ is not None and f > l_:
                        mem = mem[::-1]
            else:
                mem = sorted(mem, key=lambda n: (keyf(n) if keyf(n) is not None else pos[n], pos[n]))
            scored.append((bary, min(pos[n] for n in mem), mem))
        scored.sort(key=lambda s: (s[0], s[1]))
        order[t] = [n for _, _, mem in scored for n in mem]

    def crossings():
        pos = {n: i for row in order for i, n in enumerate(row)}
        total = 0
        by_tier = defaultdict(list)
        for h in hops:
            by_tier[items[h.upper].tier].append((pos[h.upper], pos[h.lower]))
        for segs in by_tier.values():
            for (a1, b1), (a2, b2) in itertools.combinations(segs, 2):
                if (a1 - a2) * (b1 - b2) < 0:
                    total += 1
        return total

    for t in range(len(order)):
        regroup(t, lambda n: None)
    best = (crossings(), [row[:] for row in order])
    for _ in range(12):
        for t in range(1, len(order)):
            pos = {n: i for i, n in enumerate(order[t - 1])}
            regroup(t, lambda n: (sum(pos[u] for u in up[n]) / len(up[n])) if up[n] else None)
        for t in range(len(order) - 2, -1, -1):
            pos = {n: i for i, n in enumerate(order[t + 1])}
            regroup(t, lambda n: (sum(pos[d] for d in down[n]) / len(down[n])) if down[n] else None)
        c = crossings()
        if c < best[0]:
            best = (c, [row[:] for row in order])
    order = best[1]
    pos_in_row = {n: i for row in order for i, n in enumerate(row)}

    # ---- ports -------------------------------------------------------------
    ports_by_edge = defaultdict(list)
    for h in hops:
        top_end, bot_end = edge_ends[h.edge]
        upl = _label_lines(top_end) if h.upper == top_end.device else []
        lol = _label_lines(bot_end) if h.lower == bot_end.device else []
        h.up_port = Port(item=h.upper, side="bottom", edge=h.edge, other=h.lower, lines=upl)
        h.low_port = Port(item=h.lower, side="top", edge=h.edge, other=h.upper, lines=lol)
        for p in (h.up_port, h.low_port):
            p.lw, p.lh = _label_box(p.lines)
            items[p.item].ports.append(p)
            ports_by_edge[h.edge].append(p)

    side_links, u_links = [], []
    for l in same:
        ia, ib = pos_in_row[l.a.device], pos_in_row[l.b.device]
        left, right = (l.a, l.b) if ia < ib else (l.b, l.a)
        pl = Port(item=left.device, side="right", edge=l.id, other=right.device, lines=_label_lines(left))
        pr = Port(item=right.device, side="left", edge=l.id, other=left.device, lines=_label_lines(right))
        if abs(ia - ib) != 1:
            pl.side = pr.side = "bottom"
            u_links.append((l, pl, pr))
        else:
            side_links.append((l, pl, pr))
        for p in (pl, pr):
            p.lw, p.lh = _label_box(p.lines)
            items[p.item].ports.append(p)
            ports_by_edge[l.id].append(p)

    def slot_w(p):
        return 4 + LBL_GAP + p.lw + SLOT_PAD if p.lines else 18

    for it in items.values():
        if it.dummy:
            continue
        for side in ("top", "bottom"):
            ps = [p for p in it.ports if p.side == side]
            if len(ps) == 1:
                need = 2 * (LBL_GAP + ps[0].lw + 6)
            else:
                need = sum(slot_w(p) for p in ps) + 12
            it.w = max(it.w, need)

    # ---- separations between neighbours in each row -------------------------
    side_pair = defaultdict(list)
    for l, pl, pr in side_links:
        side_pair[(pl.item, pr.item)].append((l, pl, pr))
    group_header = {}
    for t, row in enumerate(order):
        for n in row:
            b = items[n].block
            if b.startswith("vlan:"):
                group_header[b] = _label_box([TextLine(_vlan_title(topo, b[5:]), SUB_FONT, True)])

    def sep(a, b):
        ia, ib = items[a], items[b]
        gap = NODE_GAP
        if ia.dummy or ib.dummy:
            gap = 16
        if (a, b) in side_pair:
            need = max(pl.lw + pr.lw + 4 * LBL_GAP + 12 for _, pl, pr in side_pair[(a, b)])
            gap = max(gap, need)
        if ia.block != ib.block:
            for blk, it_ in ((ia.block, ia), (ib.block, ib)):
                if blk.startswith("vlan:"):
                    gap += GPAD
            if ia.block.startswith("vlan:") or ib.block.startswith("vlan:"):
                gap += GROUP_GAP
            if ia.block.startswith("vlan:"):
                mem = [n for n in order[ia.tier] if items[n].block == ia.block]
                span = sum(items[n].w for n in mem) + NODE_GAP * (len(mem) - 1)
                gap += max(0.0, group_header[ia.block][0] - span)
        return (ia.w + ib.w) / 2 + gap

    def place_ports(it):
        for side in ("top", "bottom"):
            ps = [p for p in it.ports if p.side == side]
            ps.sort(key=lambda p: (items[p.other].x, p.edge))
            if not ps:
                continue
            if it.dummy:
                for p in ps:
                    p.x = it.x
                continue
            if len(ps) == 1:
                ps[0].x = it.x
                continue
            total = sum(slot_w(p) for p in ps)
            x = it.x - total / 2
            for p in ps:
                p.x = x + 4
                x += slot_w(p)

    # initial packing
    for row in order:
        x = 0.0
        for i, n in enumerate(row):
            if i:
                x += sep(row[i - 1], n)
            items[n].x = x
    for it in items.values():
        place_ports(it)

    hop_by_port = {}
    for h in hops:
        hop_by_port[id(h.up_port)] = h.low_port
        hop_by_port[id(h.low_port)] = h.up_port

    for _ in range(40):
        for t in list(range(len(order))) + list(range(len(order) - 2, 0, -1)):
            row = order[t]
            desired, weights = [], []
            for n in row:
                it = items[n]
                vals = []
                for p in it.ports:
                    q = hop_by_port.get(id(p))
                    if q is not None:
                        vals.append(q.x - (p.x - it.x))
                if vals:
                    desired.append(sum(vals) / len(vals))
                    weights.append(float(len(vals)))
                else:
                    desired.append(it.x)
                    weights.append(0.05)
            seps = [sep(row[i], row[i + 1]) for i in range(len(row) - 1)]
            xs = _pava(desired, weights, seps)
            for n, x in zip(row, xs):
                items[n].x = x
            for n in row:
                place_ports(items[n])
            for n in row:
                for p in items[n].ports:
                    q = hop_by_port.get(id(p))
                    if q is not None:
                        place_ports(items[q.item])

    minx = min(it.x - it.w / 2 for it in items.values())
    shift = MARGIN + GUTTER - minx
    for it in items.values():
        it.x += shift
    for it in items.values():
        place_ports(it)

    # ---- horizontal tracks per channel ---------------------------------------
    nT = len(order)
    chan = defaultdict(list)   # channel index (below row t) -> list of [lo, hi, key]
    for h in hops:
        if abs(h.up_port.x - h.low_port.x) > 0.5:
            lo, hi = sorted((h.up_port.x, h.low_port.x))
            chan[items[h.upper].tier].append([lo, hi, ("hop", h)])
    for ul in u_links:
        lo, hi = sorted((ul[1].x, ul[2].x))
        chan[items[ul[1].item].tier].append([lo, hi, ("u", ul)])
    track_of = {}
    ntracks = defaultdict(int)
    for c, spans in chan.items():
        spans.sort(key=lambda s: (s[0], s[1]))
        ends = []
        assign = []
        for lo, hi, key in spans:
            for k, e in enumerate(ends):
                if e + 10 < lo:
                    ends[k] = hi
                    assign.append(k)
                    break
            else:
                ends.append(hi)
                assign.append(len(ends) - 1)
        n = len(ends)
        verts = _channel_verticals(c, hops, u_links, items)
        best_perm, best_x = None, None
        perms = itertools.permutations(range(n)) if n <= 6 else [tuple(range(n))]
        for perm in perms:
            x = _channel_crossings(spans, [perm[a] for a in assign], verts)
            if best_x is None or x < best_x:
                best_perm, best_x = perm, x
        for (lo, hi, key), a in zip(spans, assign):
            track_of[id(key[1])] = best_perm[a]
        ntracks[c] = n

    def _side_spacing(pairs):
        return max((max(pl.lh, pr.lh) for _, pl, pr in pairs), default=0) + 8

    for pairs in side_pair.values():
        n = len(pairs)
        if n < 2:
            continue
        d = _side_spacing(pairs)
        top_need = 3 + max(pl.lh for _, pl, pr in pairs)
        bot_need = 3 + max(pr.lh for _, pl, pr in pairs)
        need = (n - 1) * d + top_need + bot_need + 8
        for _, pl, pr in pairs:
            items[pl.item].h = max(items[pl.item].h, need)
            items[pr.item].h = max(items[pr.item].h, need)

    # ---- vertical placement ---------------------------------------------------
    has_groups = {t: any(items[n].block.startswith("vlan:") for n in row) for t, row in enumerate(order)}
    head_h = max([hh for _, hh in group_header.values()] or [0])
    title_lines = [TextLine(title or "Network diagram", 16, True, style.INK)]
    n_dev = len(topo.devices)
    title_lines.append(TextLine(f"{n_dev} devices · {len(links)} links · {len(topo.vlans)} VLANs",
                                SUB_FONT, False, style.MUTED))
    tw, th = _label_box(title_lines)
    y = MARGIN + th + 14
    row_top, row_h, top_boundary = {}, {}, {}
    for t, row in enumerate(order):
        tops = [p.lh for n in row for p in items[n].ports if p.side == "top"]
        zone_top = (max(tops) + 2 * ZONE_GAP) if tops else 0
        gtop = GPAD if has_groups[t] else 0
        y += zone_top + gtop
        row_top[t] = y
        top_boundary[t] = y - gtop
        hmax = max([items[n].h for n in row if not items[n].dummy] or [0])
        row_h[t] = hmax
        for n in row:
            items[n].y = y
            if items[n].dummy:
                items[n].h = hmax
        y += hmax
        if has_groups[t]:
            y += GPAD + head_h + 4
        bots = [p.lh for n in row for p in items[n].ports if p.side == "bottom"]
        zone_bot = (max(bots) + 2 * ZONE_GAP) if bots else 0
        y += zone_bot
        if t < nT - 1 or ntracks.get(t):
            row_bottom_zone_end = y
            y += (ntracks.get(t, 0) + 1) * TRACK
            items_chan_start = row_bottom_zone_end
            for h in hops:
                if items[h.upper].tier == t:
                    h.track_y = items_chan_start + (track_of.get(id(h), -1) + 1) * TRACK
            for ul in u_links:
                if items[ul[1].item].tier == t:
                    ul[1].track_y = items_chan_start + (track_of.get(id(ul), 0) + 1) * TRACK

    for it in items.values():
        for p in it.ports:
            if p.side == "top":
                p.y = it.y
            elif p.side == "bottom":
                p.y = it.y + it.h

    # ---- build scene ------------------------------------------------------------
    nodes, edges, labels, groups = [], [], [], []
    for n, it in items.items():
        if it.dummy:
            continue
        dev = it.dev
        nodes.append(Node(id=n, rect=Rect(it.x - it.w / 2, it.y, it.w, it.h), icon=dev.icon,
                          color=style.icon_color(dev.icon, dev.tier), lines=it.lines, role=dev.role,
                          notes="; ".join(r.notes for r in dev.rows if r.notes), tier=dev.tier))
    node_rect = {nd.id: nd.rect for nd in nodes}

    def port_label(p, eid):
        if not p.lines:
            return None
        if p.side == "bottom":
            r = Rect(p.x + LBL_GAP, node_rect[p.item].y2 + ZONE_GAP, p.lw, p.lh)
        elif p.side == "top":
            r = Rect(p.x + LBL_GAP, top_boundary[items[p.item].tier] - ZONE_GAP - p.lh, p.lw, p.lh)
        else:
            r = Rect(p.x, p.y, p.lw, p.lh)
        lab = Label(id=f"lbl_{eid}_{p.item}_{p.side}", rect=r, lines=p.lines, kind="port", owner=eid)
        labels.append(lab)
        return lab.id

    by_edge_hops = defaultdict(list)
    for h in hops:
        by_edge_hops[h.edge].append(h)
    for l in links:
        if l.id in by_edge_hops:
            hs = by_edge_hops[l.id]
            pts = [(hs[0].up_port.x, hs[0].up_port.y)]
            for h in hs:
                a, b = h.up_port, h.low_port
                if abs(a.x - b.x) > 0.5:
                    pts += [(a.x, h.track_y), (b.x, h.track_y)]
                pts.append((b.x, b.y))
            pts = _simplify(pts)
            top_end, bot_end = edge_ends[l.id]
            lids = [port_label(hs[0].up_port, l.id), port_label(hs[-1].low_port, l.id)]
            edges.append(Edge(id=l.id, points=pts, source=top_end.device, target=bot_end.device,
                              labels=[x for x in lids if x]))
    side_yy = {}
    for (a, b), pairs in side_pair.items():
        ra, rb = node_rect[a], node_rect[b]
        mid = max(ra.y, rb.y) + min(ra.h, rb.h) / 2
        n = len(pairs)
        d = _side_spacing(pairs) if n > 1 else 0
        y0 = mid - (n - 1) * d / 2
        for i, (l, _, _) in enumerate(pairs):
            side_yy[l.id] = y0 + i * d
    for l, pl, pr in side_links:
        ra, rb = node_rect[pl.item], node_rect[pr.item]
        yy = side_yy[l.id]
        pl.x, pl.y, pr.x, pr.y = ra.x2, yy, rb.x, yy
        lids = []
        if pl.lines:
            lab = Label(id=f"lbl_{l.id}_{pl.item}_r", rect=Rect(ra.x2 + LBL_GAP, yy - 3 - pl.lh, pl.lw, pl.lh),
                        lines=pl.lines, kind="port", owner=l.id)
            labels.append(lab)
            lids.append(lab.id)
        if pr.lines:
            lab = Label(id=f"lbl_{l.id}_{pr.item}_l",
                        rect=Rect(rb.x - LBL_GAP - pr.lw, yy + 3, pr.lw, pr.lh),
                        lines=pr.lines, kind="port", owner=l.id)
            labels.append(lab)
            lids.append(lab.id)
        edges.append(Edge(id=l.id, points=[(ra.x2, yy), (rb.x, yy)], source=pl.item, target=pr.item,
                          kind="peer", labels=lids))
    for l, pl, pr in u_links:
        ty = pl.track_y
        pts = [(pl.x, pl.y), (pl.x, ty), (pr.x, ty), (pr.x, pr.y)]
        lids = [port_label(pl, l.id), port_label(pr, l.id)]
        edges.append(Edge(id=l.id, points=pts, source=pl.item, target=pr.item, kind="peer",
                          labels=[x for x in lids if x]))

    # groups (VLAN containers in the endpoint row)
    gi = 0
    for t, row in enumerate(order):
        blocks = []
        for n in row:
            b = items[n].block
            if b.startswith("vlan:") and b not in blocks:
                blocks.append(b)
        for b in blocks:
            mem = [items[n] for n in row if items[n].block == b]
            hw, hh = group_header[b]
            x0 = min(m.x - m.w / 2 for m in mem) - GPAD
            x1 = max(max(m.x + m.w / 2 for m in mem) + GPAD, x0 + hw + 2 * GPAD)
            y0 = row_top[t] - GPAD
            y1 = row_top[t] + row_h[t] + GPAD + hh + 4
            color = style.GROUP_COLORS[gi % len(style.GROUP_COLORS)]
            gi += 1
            lab = Label(id=f"grp_lbl_{b}", rect=Rect(x0 + GPAD, y1 - 4 - hh, hw, hh),
                        lines=[TextLine(_vlan_title(topo, b[5:]), SUB_FONT, True, color)],
                        kind="group", background=False)
            labels.append(lab)
            groups.append(Group(id=f"grp_{b}", rect=Rect(x0, y0, x1 - x0, y1 - y0), label=lab.id, color=color,
                                members=[m.id for m in mem]))

    # row titles in the left gutter
    for t, row in enumerate(order):
        tl = [TextLine(TIER_TITLES[present[t]].upper(), 9, True, "#94a3b8")]
        w_, h_ = _label_box(tl)
        labels.append(Label(id=f"tier_{t}", rect=Rect(MARGIN, row_top[t] + row_h[t] / 2 - h_ / 2, w_, h_),
                            lines=tl, kind="tier", background=False))

    labels.append(Label(id="title", rect=Rect(MARGIN, MARGIN, tw, th), lines=title_lines, kind="title",
                        background=False))
    return _finish(topo, Scene(0, 0, nodes, edges, labels, groups, title=title), links)


def _channel_verticals(c, hops, u_links, items):
    """Vertical segments inside channel c: (x, kind, key) kind: top (from row
    above down to its track), bottom (from track down to row below), full."""
    out = []
    for h in hops:
        if items[h.upper].tier != c:
            continue
        if abs(h.up_port.x - h.low_port.x) <= 0.5:
            out.append((h.up_port.x, "full", id(h)))
        else:
            out.append((h.up_port.x, "top", id(h)))
            out.append((h.low_port.x, "bottom", id(h)))
    for ul in u_links:
        if items[ul[1].item].tier == c:
            out.append((ul[1].x, "top", id(ul)))
            out.append((ul[2].x, "top", id(ul)))
    return out


def _channel_crossings(spans, tracks, verts):
    trk = {id(s[2][1]): t for s, t in zip(spans, tracks)}
    n = 0
    for (lo, hi, key), t in zip(spans, tracks):
        for x, kind, vk in verts:
            if vk == id(key[1]) or not (lo + 0.5 < x < hi - 0.5):
                continue
            if kind == "full":
                n += 1
            elif kind == "top" and trk.get(vk, -1) > t:
                n += 1
            elif kind == "bottom" and trk.get(vk, 99) < t:
                n += 1
    return n


def _simplify(pts):
    out = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 0.01 and abs(out[-1][1] - p[1]) < 0.01:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or \
           (abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01):
            out.pop(i)
        else:
            i += 1
    return out


def _subnet_rows(topo, links):
    nets = {}
    for v in topo.vlans.values():
        net = v.network
        if net is not None:
            nets[net] = f"VLAN {v.vid} {v.name}"
    for l in links:
        ia, ib = parse_cidr(l.a.address), parse_cidr(l.b.address)
        if ia is not None and ib is not None and ia.network == ib.network and ia.network not in nets:
            nets[ia.network] = f"{l.a.device} {l.a.port} ↔ {l.b.device} {l.b.port}".replace("  ", " ")
    for d in topo.devices.values():
        for r in d.rows:
            ip = parse_cidr(r.address)
            if ip is not None and ip.network not in nets:
                nets[ip.network] = f"{d.name} {r.interface}".strip()
    return sorted(nets.items(), key=lambda kv: (kv[0].version, kv[0]))


def _finish(topo, scene: Scene, links) -> Scene:
    """Add the subnet table below everything and compute the canvas size."""
    rects = [n.rect for n in scene.nodes] + [l.rect for l in scene.labels] + [g.rect for g in scene.groups]
    pts = [p for e in scene.edges for p in e.points]
    bottom = max([r.y2 for r in rects] + [p[1] for p in pts])
    rows = _subnet_rows(topo, links)
    if rows:
        from .text import text_width
        col1 = max(text_width(str(n), SUB_FONT) for n, _ in rows) + 18
        lines = [TextLine("Subnets", 11, True, style.INK)]
        widest = text_width("Subnets", 11, True)
        for net, desc in rows:
            lines.append(TextLine(f"{net}\t{desc}", SUB_FONT, False, style.INK))
            widest = max(widest, col1 + text_width(desc, SUB_FONT))
        _, h = _label_box(lines)
        r = Rect(MARGIN, bottom + 28, widest + 16 + 2 * LPAD_X, h + 12)
        scene.labels.append(Label(id="legend", rect=r, lines=lines, kind="legend", tab=col1))
        scene.legend_rect = r
    rects = [n.rect for n in scene.nodes] + [l.rect for l in scene.labels] + [g.rect for g in scene.groups]
    scene.width = max([r.x2 for r in rects] + [p[0] for p in pts]) + MARGIN
    scene.height = max([r.y2 for r in rects] + [p[1] for p in pts]) + MARGIN
    return scene


# ----------------------------------------------------------------------------
def layout_inventory(topo: Topology, title: str = "") -> Scene:
    """No links in the input: show an inventory grouped by subnet."""
    groups_map = defaultdict(list)
    keys = {}
    for dev in topo.devices.values():
        vid = topo.device_vlan(dev)
        if vid and vid in topo.vlans:
            key = ("vlan", vid)
            keys[key] = _vlan_title(topo, vid)
        else:
            ip = next((r.iface for r in dev.rows if r.iface is not None), None)
            if ip is None:
                key = ("none", "")
                keys[key] = "No address"
            else:
                key = ("net", str(ip.network))
                keys[key] = f"Subnet {ip.network}"
        groups_map[key].append(dev)

    def sort_key(k):
        if k[0] == "vlan":
            net = topo.vlans[k[1]].network or ipaddress.ip_network("0.0.0.0/0")
            return (0, net.version, net)
        if k[0] == "net":
            net = ipaddress.ip_network(k[1])
            return (0, net.version, net)
        return (1, 4, ipaddress.ip_network("0.0.0.0/0"))

    title_lines = [TextLine(title or "Network inventory", 16, True, style.INK),
                   TextLine(f"{len(topo.devices)} devices · no links in input, grouped by subnet",
                            SUB_FONT, False, style.MUTED)]
    tw, th = _label_box(title_lines)
    nodes, labels, groups = [], [], []
    labels.append(Label(id="title", rect=Rect(MARGIN, MARGIN, tw, th), lines=title_lines, kind="title",
                        background=False))
    max_w = 1400
    x, y = MARGIN, MARGIN + th + 20
    row_h = 0
    for gi, key in enumerate(sorted(groups_map, key=sort_key)):
        devs = sorted(groups_map[key], key=lambda d: (TIERS.index(d.tier), d.name))
        sized = []
        for d in devs:
            lines = [TextLine(d.name, NAME_FONT, True, style.INK),
                     TextLine(style.caption(d.icon, d.tier), SUB_FONT, False, style.MUTED)]
            for r in d.rows:
                if r.address:
                    lines.append(TextLine(f"{(r.interface + ' ') if r.interface else ''}{r.address}",
                                          SUB_FONT, False, style.ADDR))
            sized.append((d, lines, *_node_size(lines)))
        color = style.GROUP_COLORS[gi % len(style.GROUP_COLORS)]
        head = [TextLine(keys[key], SUB_FONT, True, color)]
        hw, hh = _label_box(head)
        per_row = 4
        cols = [sized[i:i + per_row] for i in range(0, len(sized), per_row)]
        inner_w = max([sum(s[2] for s in c) + NODE_GAP * (len(c) - 1) for c in cols] + [hw])
        inner_h = sum(max(s[3] for s in c) for c in cols) + 16 * (len(cols) - 1)
        gw, gh = inner_w + 2 * GPAD, inner_h + hh + 3 * GPAD
        if x > MARGIN and x + gw > max_w:
            x, y = MARGIN, y + row_h + GROUP_GAP
            row_h = 0
        g_lab = Label(id=f"grp_lbl_{gi}", rect=Rect(x + GPAD, y + GPAD / 2, hw, hh), lines=head,
                      kind="group", background=False)
        labels.append(g_lab)
        groups.append(Group(id=f"grp_{gi}", rect=Rect(x, y, gw, gh), label=g_lab.id, color=color,
                            members=[d.name for d in devs]))
        cy = y + GPAD + hh + GPAD / 2
        for c in cols:
            cx = x + GPAD
            for d, lines, w, h in c:
                nodes.append(Node(id=d.name, rect=Rect(cx, cy, w, h), icon=d.icon,
                                  color=style.icon_color(d.icon, d.tier), lines=lines, role=d.role,
                                  notes="; ".join(r.notes for r in d.rows if r.notes), tier=d.tier))
                cx += w + NODE_GAP
            cy += max(s[3] for s in c) + 16
        x += gw + GROUP_GAP
        row_h = max(row_h, gh)
    return _finish(topo, Scene(0, 0, nodes, [], labels, groups, title=title), [])

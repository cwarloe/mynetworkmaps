"""PNG output drawn directly with Pillow (no Cairo or browser needed, so it
works on Windows with a plain pip install). Draws the same scene as the SVG."""
import math

from PIL import Image, ImageDraw

from . import style
from .text import font, line_height

SUPER = 2  # supersampling factor before the final downscale


def _hex(c, alpha=255):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def _blend(color, alpha, bg="#ffffff"):
    a = _hex(color)
    b = _hex(bg)
    return tuple(round(a[i] * alpha + b[i] * (1 - alpha)) for i in range(3)) + (255,)


def _dashed(d, p0, p1, fill, width, dash, gap):
    (x0, y0), (x1, y1) = p0, p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length == 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    t = 0.0
    while t < length:
        t2 = min(t + dash, length)
        d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * t2, y0 + uy * t2)], fill=fill, width=width)
        t = t2 + gap


def _icon(d, icon, color, x, y, size, k):
    s = size / 32.0 * k
    X = lambda v: x * k + v * s
    Y = lambda v: y * k + v * s
    d.rounded_rectangle([X(0), Y(0), X(32), Y(32)], radius=7 * s, fill=_hex(color))
    white = (255, 255, 255, 255)
    for op in style.ICONS.get(icon, style.ICONS["pc"]):
        kind = op[0]
        if kind == "line":
            pts = [(X(px), Y(py)) for px, py in op[1]]
            w = max(1, round(op[2] * s))
            d.line(pts, fill=white, width=w, joint="curve")
            for px, py in pts:
                r = w / 2
                d.ellipse([px - r, py - r, px + r, py + r], fill=white)
        elif kind == "rect":
            _, rx, ry, rw, rh, rr, filled = op
            box = [X(rx), Y(ry), X(rx + rw), Y(ry + rh)]
            if filled:
                d.rounded_rectangle(box, radius=rr * s, fill=white)
            else:
                d.rounded_rectangle(box, radius=rr * s, outline=white, width=max(1, round(1.8 * s)))
        elif kind == "circle":
            _, cx, cy, r, filled, sw = op
            box = [X(cx - r), Y(cy - r), X(cx + r), Y(cy + r)]
            if filled:
                d.ellipse(box, fill=white)
            else:
                d.ellipse(box, outline=white, width=max(1, round(sw * s)))
        elif kind == "arc":
            _, cx, cy, r, a0, a1, sw = op
            d.arc([X(cx - r), Y(cy - r), X(cx + r), Y(cy + r)], a0, a1, fill=white, width=max(1, round(sw * s)))


def _text(d, x, y, lines, k, tab=0.0):
    cy = y
    for ln in lines:
        f = font(ln.size, ln.bold, k)
        lh = line_height(ln.size)
        parts = ln.text.split("\t") if tab else [ln.text]
        for i, part in enumerate(parts):
            d.text(((x + i * tab) * k, (cy + lh * 0.78) * k), part, font=f, fill=_hex(ln.color), anchor="ls")
        cy += lh


def render_png(scene, path, scale: float = 2.0):
    k = scale * SUPER
    W, H = math.ceil(scene.width * k), math.ceil(scene.height * k)
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for g in scene.groups:
        r = g.rect
        box = [r.x * k, r.y * k, r.x2 * k, r.y2 * k]
        d.rounded_rectangle(box, radius=10 * k, fill=_blend(g.color, 0.05))
        col = _blend(g.color, 0.7)
        w = max(1, round(1.2 * k))
        # dashed outline (straight parts only; corners are tiny)
        rad = 10
        for p0, p1 in [((r.x + rad, r.y), (r.x2 - rad, r.y)), ((r.x2, r.y + rad), (r.x2, r.y2 - rad)),
                       ((r.x2 - rad, r.y2), (r.x + rad, r.y2)), ((r.x, r.y2 - rad), (r.x, r.y + rad))]:
            _dashed(d, (p0[0] * k, p0[1] * k), (p1[0] * k, p1[1] * k), col, w, 6 * k, 4 * k)
        for cx, cy, a0 in [(r.x + rad, r.y + rad, 180), (r.x2 - rad, r.y + rad, 270),
                           (r.x2 - rad, r.y2 - rad, 0), (r.x + rad, r.y2 - rad, 90)]:
            d.arc([(cx - rad) * k, (cy - rad) * k, (cx + rad) * k, (cy + rad) * k], a0, a0 + 90, fill=col, width=w)
    for e in scene.edges:
        color = _hex(style.HA_LINE if e.kind == "peer" else style.LINE)
        w = max(1, round(1.6 * k))
        pts = [(x * k, y * k) for x, y in e.points]
        if e.kind == "peer":
            for a, b in zip(pts, pts[1:]):
                _dashed(d, a, b, color, w, 5 * k, 3 * k)
        else:
            d.line(pts, fill=color, width=w, joint="curve")
    for n in scene.nodes:
        r = n.rect
        d.rounded_rectangle([(r.x + 1) * k, (r.y + 2) * k, (r.x2 + 1) * k, (r.y2 + 2) * k], radius=8 * k,
                            fill=_blend("#0f172a", 0.07))
        d.rounded_rectangle([r.x * k, r.y * k, r.x2 * k, r.y2 * k], radius=8 * k, fill=(255, 255, 255, 255),
                            outline=_hex("#cbd5e1"), width=max(1, round(1 * k)))
        d.rounded_rectangle([r.x * k, (r.y + 6) * k, (r.x + 3) * k, (r.y2 - 6) * k], radius=1.5 * k,
                            fill=_hex(n.color))
        _icon(d, n.icon, n.color, r.x + 10, r.cy - 16, 32, k)
        th = sum(line_height(l.size) for l in n.lines)
        _text(d, r.x + 52, r.cy - th / 2, n.lines, k)
    for l in scene.labels:
        r = l.rect
        if l.kind == "legend":
            d.rounded_rectangle([r.x * k, r.y * k, r.x2 * k, r.y2 * k], radius=8 * k, fill=_hex("#f8fafc"),
                                outline=_hex("#e2e8f0"), width=max(1, round(k)))
            _text(d, r.x + 8, r.y + 6, l.lines, k, tab=l.tab)
            continue
        if l.background:
            d.rounded_rectangle([r.x * k, r.y * k, r.x2 * k, r.y2 * k], radius=2 * k, fill=(255, 255, 255, 255))
        _text(d, r.x + 3, r.y + 2, l.lines, k)
    out = img.resize((math.ceil(scene.width * scale), math.ceil(scene.height * scale)), Image.LANCZOS)
    out.convert("RGB").save(path, optimize=True)

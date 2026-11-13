"""SVG output (self-contained, no external assets)."""
from xml.sax.saxutils import escape

from . import style
from .text import FONT_STACK, line_height


def _text_block(x, y, lines, anchor="start", tab=0.0):
    out, cy = [], y
    for ln in lines:
        lh = line_height(ln.size)
        base = cy + lh * 0.78
        weight = ' font-weight="bold"' if ln.bold else ""
        parts = ln.text.split("\t") if tab else [ln.text]
        for i, part in enumerate(parts):
            out.append(f'<text x="{x + i * tab:.1f}" y="{base:.1f}" font-size="{ln.size}"{weight} '
                       f'fill="{ln.color}" text-anchor="{anchor}">{escape(part)}</text>')
        cy += lh
    return "".join(out)


def render_svg(scene) -> str:
    W, H = scene.width, scene.height
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
         f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT_STACK}">',
         f'<rect width="100%" height="100%" fill="#ffffff"/>']
    labels = {l.id: l for l in scene.labels}
    for g in scene.groups:
        r = g.rect
        o.append(f'<rect x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" rx="10" '
                 f'fill="{g.color}" fill-opacity="0.05" stroke="{g.color}" stroke-opacity="0.7" '
                 f'stroke-width="1.2" stroke-dasharray="6 4"/>')
    for e in scene.edges:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in e.points)
        color = style.HA_LINE if e.kind == "peer" else style.LINE
        dash = ' stroke-dasharray="5 3"' if e.kind == "peer" else ""
        o.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"{dash} '
                 f'stroke-linejoin="round"/>')
    for n in scene.nodes:
        r = n.rect
        o.append(f'<rect x="{r.x + 1:.1f}" y="{r.y + 2:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" rx="8" '
                 f'fill="#0f172a" fill-opacity="0.07"/>')
        o.append(f'<rect x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" rx="8" '
                 f'fill="#ffffff" stroke="#cbd5e1" stroke-width="1"/>')
        o.append(f'<rect x="{r.x:.1f}" y="{r.y + 6:.1f}" width="3" height="{r.h - 12:.1f}" rx="1.5" fill="{n.color}"/>')
        o.append(style.icon_svg(n.icon, n.color, r.x + 10, r.cy - 16, 32))
        th = sum(line_height(l.size) for l in n.lines)
        o.append(_text_block(r.x + 52, r.cy - th / 2, n.lines))
    for l in scene.labels:
        r = l.rect
        if l.kind == "legend":
            o.append(f'<rect x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" rx="8" '
                     f'fill="#f8fafc" stroke="#e2e8f0"/>')
            o.append(_text_block(r.x + 8, r.y + 6, l.lines, tab=l.tab))
            continue
        if l.background:
            o.append(f'<rect x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" rx="2" '
                     f'fill="#ffffff" fill-opacity="0.92"/>')
        o.append(_text_block(r.x + 3, r.y + 2, l.lines))
    o.append("</svg>")
    return "\n".join(o)

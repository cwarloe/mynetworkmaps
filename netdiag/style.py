"""Colors, captions and self-authored generic icons.

Icons are simple vector primitives on a 32x32 grid (white glyph on a colored
rounded tile). They are original drawings, not vendor stencils, and the same
primitives feed the SVG, PNG and draw.io outputs.
"""

TIER_COLORS = {
    "edge": "#475569", "firewall": "#dc2626", "core": "#1d4ed8",
    "distribution": "#2563eb", "access": "#0891b2", "endpoint": "#0f766e",
}
ICON_COLORS = {"ap": "#7c3aed", "server": "#b45309", "pc": "#0f766e",
               "printer": "#4b5563", "phone": "#4b5563", "cloud": "#64748b"}
CAPTIONS = {
    "router": "Edge router", "cloud": "Internet / ISP", "firewall": "Firewall",
    "l3switch": "Layer 3 switch", "switch": "Access switch", "ap": "Wireless AP",
    "pc": "Workstation", "server": "Server", "printer": "Printer", "phone": "IP phone",
}
TIER_CAPTION = {"core": "Core switch", "distribution": "Distribution switch"}

INK = "#1f2937"
MUTED = "#6b7280"
ADDR = "#1d4ed8"
LINE = "#334155"
HA_LINE = "#dc2626"
GROUP_COLORS = ["#0f766e", "#7c3aed", "#b45309", "#be185d", "#4d7c0f", "#0369a1"]

W = "#ffffff"

# Primitive ops (coordinates in a 32x32 box):
#   ("line", [(x, y), ...], width)          polyline, white stroke
#   ("rect", x, y, w, h, radius, filled)    white fill or white outline
#   ("circle", cx, cy, r, filled, width)
#   ("arc", cx, cy, r, start_deg, end_deg, width)   angles clockwise from +x (SVG/PIL)


def _arrow(x1, y1, x2, y2, head=3.2):
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    a1 = ang + math.radians(150)
    a2 = ang - math.radians(150)
    return [("line", [(x1, y1), (x2, y2)], 2.0),
            ("line", [(x2 + head * math.cos(a1), y2 + head * math.sin(a1)), (x2, y2),
                      (x2 + head * math.cos(a2), y2 + head * math.sin(a2))], 2.0)]


ICONS = {
    "router": [("circle", 16, 16, 9.5, False, 2.0)] + _arrow(11, 11, 6.5, 6.5) +
              _arrow(21, 21, 25.5, 25.5) + _arrow(21, 11, 25.5, 6.5) + _arrow(11, 21, 6.5, 25.5),
    "switch": _arrow(7, 12, 25, 12) + _arrow(25, 20, 7, 20),
    "l3switch": _arrow(6, 12, 20, 12) + _arrow(20, 20, 6, 20) + _arrow(25, 22, 25, 7) +
                [("line", [(23, 26), (27, 26)], 2.0)],
    "firewall": [("rect", 6, 7, 20, 18, 1.5, False),
                 ("line", [(6, 13), (26, 13)], 1.6), ("line", [(6, 19), (26, 19)], 1.6),
                 ("line", [(16, 7), (16, 13)], 1.6), ("line", [(11, 13), (11, 19)], 1.6),
                 ("line", [(21, 13), (21, 19)], 1.6), ("line", [(16, 19), (16, 25)], 1.6)],
    "ap": [("circle", 16, 22, 2.2, True, 0), ("arc", 16, 22, 6.5, 225, 315, 2.0),
           ("arc", 16, 22, 11, 225, 315, 2.0)],
    "pc": [("rect", 6, 7, 20, 14, 1.5, False), ("line", [(16, 21), (16, 25)], 2.0),
           ("line", [(11, 25.5), (21, 25.5)], 2.0)],
    "server": [("rect", 8, 6, 16, 9, 1.5, False), ("rect", 8, 17, 16, 9, 1.5, False),
               ("circle", 12, 10.5, 1.2, True, 0), ("circle", 12, 21.5, 1.2, True, 0),
               ("line", [(16, 10.5), (21, 10.5)], 1.6), ("line", [(16, 21.5), (21, 21.5)], 1.6)],
    "cloud": [("circle", 12, 18, 5.5, True, 0), ("circle", 18, 14, 6.5, True, 0),
              ("circle", 23, 19, 4.5, True, 0), ("rect", 9, 18, 16, 5.5, 2, True)],
    "printer": [("rect", 10, 6, 12, 6, 0.5, False), ("rect", 6, 12, 20, 9, 1.5, False),
                ("rect", 10, 18, 12, 8, 0.5, True)],
    "phone": [("rect", 11, 5, 10, 22, 2, False), ("line", [(14.5, 23), (17.5, 23)], 2.0)],
}


def icon_color(icon: str, tier: str) -> str:
    return ICON_COLORS.get(icon, TIER_COLORS.get(tier, "#475569"))


def caption(icon: str, tier: str) -> str:
    if icon == "l3switch":
        return TIER_CAPTION.get(tier, CAPTIONS["l3switch"])
    return CAPTIONS.get(icon, tier.title())


def icon_svg(icon: str, color: str, x: float = 0, y: float = 0, size: float = 32,
             standalone: bool = False) -> str:
    """SVG markup for an icon tile at (x, y)."""
    import math
    s = size / 32.0
    parts = [f'<rect x="0" y="0" width="32" height="32" rx="7" fill="{color}"/>']
    for op in ICONS.get(icon, ICONS["pc"]):
        kind = op[0]
        if kind == "line":
            pts = " ".join(f"{px:.2f},{py:.2f}" for px, py in op[1])
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{W}" stroke-width="{op[2]}" '
                         f'stroke-linecap="round" stroke-linejoin="round"/>')
        elif kind == "rect":
            _, rx_, ry_, rw, rh, rr, filled = op
            paint = f'fill="{W}"' if filled else f'fill="none" stroke="{W}" stroke-width="1.8"'
            parts.append(f'<rect x="{rx_}" y="{ry_}" width="{rw}" height="{rh}" rx="{rr}" {paint}/>')
        elif kind == "circle":
            _, cx, cy, r, filled, sw = op
            paint = f'fill="{W}"' if filled else f'fill="none" stroke="{W}" stroke-width="{sw}"'
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" {paint}/>')
        elif kind == "arc":
            _, cx, cy, r, a0, a1, sw = op
            x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
            x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
            parts.append(f'<path d="M{x0:.2f},{y0:.2f} A{r},{r} 0 0 1 {x1:.2f},{y1:.2f}" fill="none" '
                         f'stroke="{W}" stroke-width="{sw}" stroke-linecap="round"/>')
    inner = "".join(parts)
    if standalone:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
                f'viewBox="0 0 32 32">{inner}</svg>')
    return f'<g transform="translate({x:.2f},{y:.2f}) scale({s:.4f})">{inner}</g>'

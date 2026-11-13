"""Editable draw.io (diagrams.net) output.

Every device is a native vertex (with its icon embedded in the style), every
link is a native orthogonal edge connected to both devices with fixed port
points and waypoints, and port labels are edge labels, so they move with the
link when you drag things in draw.io. VLAN containers are plain shapes.
"""
import base64
from xml.sax.saxutils import escape


def quoteattr(s):
    return '"' + escape(s, {'"': '&quot;', '\n': '&#10;'}) + '"'

from . import style
from .text import line_height

FONT = "Verdana"


def _html(lines):
    parts = []
    for ln in lines:
        t = escape(ln.text)
        if ln.bold:
            t = f"<b>{t}</b>"
        parts.append(f'<font style="font-size:{ln.size}px" color="{ln.color}">{t}</font>')
    return "<br>".join(parts)


def _icon_uri(icon, color):
    svg = style.icon_svg(icon, color, standalone=True)
    return "data:image/svg+xml," + base64.b64encode(svg.encode()).decode()


def _rel(pt, rect):
    return ((pt[0] - rect.x) / rect.w if rect.w else 0.5, (pt[1] - rect.y) / rect.h if rect.h else 0.5)


def render_drawio(scene, name="Network") -> str:
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    labels = {l.id: l for l in scene.labels}
    used = set()
    for g in scene.groups:
        r = g.rect
        lab = labels[g.label]
        used.add(lab.id)
        st = (f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;dashed=1;dashPattern=6 4;fillColor={g.color};"
              f"opacity=100;fillOpacity=6;strokeColor={g.color};verticalAlign=bottom;align=left;"
              f"spacingLeft=10;spacingBottom=2;fontFamily={FONT};fontSize=10;fontStyle=1;fontColor={g.color};")
        cells.append(f'<mxCell id="{escape(g.id)}" value={quoteattr(lab.lines[0].text)} style="{st}" vertex="1" '
                     f'parent="1"><mxGeometry x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" '
                     f'as="geometry"/></mxCell>')
    node_rect = {}
    for n in scene.nodes:
        r = n.rect
        node_rect[n.id] = r
        st = (f"shape=label;rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#cbd5e1;"
              f"shadow=1;image={_icon_uri(n.icon, n.color)};imageWidth=32;imageHeight=32;imageAlign=left;"
              f"imageVerticalAlign=middle;spacingLeft=42;align=left;verticalAlign=middle;fontFamily={FONT};")
        tip = f' tooltip={quoteattr(n.notes)}' if n.notes else ""
        cells.append(f'<UserObject id={quoteattr("dev_" + n.id)} label={quoteattr(_html(n.lines))} '
                     f'role={quoteattr(n.role)}{tip}><mxCell style="{st}" vertex="1" parent="1">'
                     f'<mxGeometry x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" '
                     f'as="geometry"/></mxCell></UserObject>')
    for e in scene.edges:
        sr, tr = node_rect[e.source], node_rect[e.target]
        p0, p1 = e.points[0], e.points[-1]
        ex, ey = _rel(p0, sr)
        nx, ny = _rel(p1, tr)
        color = style.HA_LINE if e.kind == "peer" else style.LINE
        dash = "dashed=1;" if e.kind == "peer" else ""
        st = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=none;startArrow=none;strokeWidth=1.6;"
              f"strokeColor={color};{dash}exitX={ex:.4f};exitY={ey:.4f};exitDx=0;exitDy=0;"
              f"entryX={nx:.4f};entryY={ny:.4f};entryDx=0;entryDy=0;")
        way = "".join(f'<mxPoint x="{x:.1f}" y="{y:.1f}"/>' for x, y in e.points[1:-1])
        eid = "link_" + e.id
        cells.append(f'<mxCell id="{eid}" style="{st}" edge="1" parent="1" source={quoteattr("dev_" + e.source)} '
                     f'target={quoteattr("dev_" + e.target)}><mxGeometry relative="1" as="geometry">'
                     f'<Array as="points">{way}</Array></mxGeometry></mxCell>')
        for i, lid in enumerate(e.labels):
            lab = labels[lid]
            used.add(lid)
            r = lab.rect
            # anchor at whichever end of the link this label belongs to
            d0 = abs(r.cx - p0[0]) + abs(r.cy - p0[1])
            d1 = abs(r.cx - p1[0]) + abs(r.cy - p1[1])
            end, ax = (p0, -1) if d0 <= d1 else (p1, 1)
            st = (f"edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;labelBackgroundColor=#ffffff;"
                  f"fontFamily={FONT};spacing=2;")
            cells.append(f'<mxCell id="{eid}_l{i}" value={quoteattr(_html(lab.lines))} style="{st}" vertex="1" '
                         f'connectable="0" parent="{eid}"><mxGeometry x="{ax}" relative="1" as="geometry">'
                         f'<mxPoint x="{r.cx - end[0]:.1f}" y="{r.cy - end[1]:.1f}" as="offset"/></mxGeometry></mxCell>')
    for lab in scene.labels:
        if lab.id in used:
            continue
        r = lab.rect
        if lab.kind == "legend":
            text = "<br>".join(escape(l.text).replace("\t", "&nbsp;&nbsp;&nbsp;") if not l.bold else
                               f"<b>{escape(l.text)}</b>" for l in lab.lines)
            st = (f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#e2e8f0;align=left;"
                  f"verticalAlign=top;spacingLeft=8;spacingTop=4;fontFamily={FONT};fontSize=10;")
            # legend second column: draw.io html has no tab stops, so widen a little
            cells.append(f'<mxCell id="legend" value={quoteattr(text)} style="{st}" vertex="1" parent="1">'
                         f'<mxGeometry x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w + 40:.1f}" height="{r.h:.1f}" '
                         f'as="geometry"/></mxCell>')
            continue
        st = f"text;html=1;align=left;verticalAlign=top;spacing=2;fontFamily={FONT};"
        cells.append(f'<mxCell id={quoteattr(lab.id)} value={quoteattr(_html(lab.lines))} style="{st}" vertex="1" '
                     f'parent="1"><mxGeometry x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w + 8:.1f}" '
                     f'height="{r.h:.1f}" as="geometry"/></mxCell>')
    body = "".join(cells)
    return (f'<mxfile host="netdiag" type="device"><diagram id="netdiag" name={quoteattr(name)}>'
            f'<mxGraphModel dx="{scene.width:.0f}" dy="{scene.height:.0f}" grid="1" gridSize="10" guides="1" '
            f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{scene.width:.0f}" '
            f'pageHeight="{scene.height:.0f}" math="0" shadow="0"><root>{body}</root></mxGraphModel></diagram></mxfile>')

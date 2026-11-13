"""Plain geometry produced by the layout and consumed by every renderer and
by the overlap checker."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self):
        return self.x + self.w

    @property
    def y2(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def intersects(self, o: "Rect", tol: float = 0.5) -> bool:
        return (self.x < o.x2 - tol and o.x < self.x2 - tol and
                self.y < o.y2 - tol and o.y < self.y2 - tol)

    def inset(self, d: float) -> "Rect":
        return Rect(self.x + d, self.y + d, self.w - 2 * d, self.h - 2 * d)


@dataclass
class TextLine:
    text: str
    size: float
    bold: bool = False
    color: str = "#1f2937"


@dataclass
class Label:
    id: str
    rect: Rect
    lines: list            # list[TextLine]
    kind: str              # port | group | tier | title | legend
    owner: str = ""        # edge id for port labels
    align: str = "left"
    background: bool = True
    tab: float = 0.0        # legend: x offset of the second column (text after a tab)


@dataclass
class Node:
    id: str
    rect: Rect
    icon: str
    color: str
    lines: list            # list[TextLine] drawn inside the box
    role: str = ""
    notes: str = ""
    tier: str = ""


@dataclass
class Edge:
    id: str
    points: list           # [(x, y), ...] orthogonal polyline
    source: str
    target: str
    kind: str = "link"     # link | ha
    labels: list = field(default_factory=list)  # label ids


@dataclass
class Group:
    id: str
    rect: Rect
    label: str             # label id
    color: str = "#64748b"
    members: list = field(default_factory=list)  # node ids inside the group


@dataclass
class Scene:
    width: float
    height: float
    nodes: list
    edges: list
    labels: list
    groups: list
    title: str = ""
    legend_rect: Rect | None = None

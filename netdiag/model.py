"""CSV loading and the in-memory topology model.

Every value is kept exactly as written in the CSV (only surrounding spaces are
trimmed). Parsing helpers never rewrite an address; validation reports problems
instead of fixing them.
"""
from __future__ import annotations

import csv
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

COLUMNS = ["name", "role", "address", "interface", "vlan",
           "connected_to", "local_port", "remote_port", "notes"]
REQUIRED_COLUMNS = ["name", "role", "address"]

# role keyword -> (tier index, icon name). Tiers are drawn top to bottom.
TIERS = ["edge", "firewall", "core", "distribution", "access", "endpoint"]
TIER_TITLES = {"edge": "Edge / WAN", "firewall": "Firewall", "core": "Core",
               "distribution": "Distribution", "access": "Access",
               "endpoint": "Endpoints"}
ROLE_ALIASES = {
    "edge": ("edge", "router"), "wan": ("edge", "router"), "router": ("edge", "router"),
    "isp": ("edge", "cloud"), "internet": ("edge", "cloud"), "cloud": ("edge", "cloud"),
    "firewall": ("firewall", "firewall"), "fw": ("firewall", "firewall"),
    "core": ("core", "l3switch"),
    "distribution": ("distribution", "l3switch"), "dist": ("distribution", "l3switch"),
    "access": ("access", "switch"), "switch": ("access", "switch"),
    "ap": ("endpoint", "ap"), "wap": ("endpoint", "ap"), "wifi": ("endpoint", "ap"),
    "pc": ("endpoint", "pc"), "workstation": ("endpoint", "pc"), "laptop": ("endpoint", "pc"),
    "endpoint": ("endpoint", "pc"), "host": ("endpoint", "pc"),
    "server": ("endpoint", "server"), "printer": ("endpoint", "printer"),
    "phone": ("endpoint", "phone"),
}
VLAN_ROLE = "vlan"


@dataclass
class Row:
    line: int                     # 1-based line number in the CSV (header is line 1)
    name: str
    role: str
    address: str
    interface: str
    vlan: str
    connected_to: str
    local_port: str
    remote_port: str
    notes: str
    extra: list = field(default_factory=list)  # fields past the last header column, kept verbatim

    @property
    def iface(self):
        """Parsed address as ipaddress interface, or None if blank/invalid."""
        return parse_cidr(self.address)


@dataclass
class Vlan:
    vid: str
    name: str
    subnet: str
    line: int

    @property
    def network(self):
        try:
            return ipaddress.ip_network(self.subnet, strict=True)
        except ValueError:
            return None


@dataclass
class Device:
    name: str
    role: str
    rows: list = field(default_factory=list)

    @property
    def tier(self):
        return ROLE_ALIASES.get(self.role.lower(), ("endpoint", "pc"))[0]

    @property
    def icon(self):
        return ROLE_ALIASES.get(self.role.lower(), ("endpoint", "pc"))[1]

    def row_for_port(self, port):
        if not port:
            return None
        for r in self.rows:
            if (r.local_port or r.interface) == port:
                return r
        return None


@dataclass
class LinkEnd:
    device: str
    port: str            # may be ""
    row: Row | None      # the CSV row describing this interface, if any

    @property
    def address(self):
        return self.row.address if self.row and self.row.address else ""

    @property
    def vlan(self):
        return self.row.vlan if self.row and self.row.vlan else ""


@dataclass
class Link:
    id: str
    a: LinkEnd
    b: LinkEnd
    lines: list           # CSV lines that declared this link


@dataclass
class Topology:
    rows: list
    devices: dict         # name -> Device (insertion ordered)
    vlans: dict           # vid -> Vlan
    links: list
    header_errors: list = field(default_factory=list)
    ambiguous: list = field(default_factory=list)  # (line, [link ids]) rows that match more than one link
    unknown_columns: list = field(default_factory=list)
    duplicate_columns: list = field(default_factory=list)

    def device_vlan(self, dev: Device):
        """VLAN id an endpoint belongs to: explicit vlan column first, else the
        VLAN whose subnet contains its address. Never changes input values."""
        for r in dev.rows:
            if r.vlan:
                return r.vlan
        for r in dev.rows:
            ip = r.iface
            if ip is None:
                continue
            for v in self.vlans.values():
                net = v.network
                if net is not None and ip.ip in net:
                    return v.vid
        return ""

    @property
    def has_links(self):
        return bool(self.links)


def parse_cidr(text):
    """Parse 'a.b.c.d/len' (or IPv6). Requires an explicit prefix length."""
    if not text or "/" not in text:
        return None
    try:
        return ipaddress.ip_interface(text)
    except ValueError:
        return None


def load_csv(path) -> Topology:
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip().lower() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        header_errors = [f"missing required column '{c}'" for c in REQUIRED_COLUMNS
                         if c not in header]
        unknown_columns = [h for h in header if h and h not in COLUMNS]
        duplicate_columns = [h for h in sorted(set(header)) if h and header.count(h) > 1]
        rows = []
        for i, raw in enumerate(reader, start=2):
            vals = {c: (raw.get(c) or "").strip() for c in COLUMNS}
            if not any(vals.values()):
                continue
            extra = ([raw[""]] if raw.get("") else []) + list(raw.get(None) or [])
            rows.append(Row(line=i, **vals, extra=extra))
    return build_topology(rows, header_errors, unknown_columns, duplicate_columns)


def build_topology(rows, header_errors=None, unknown_columns=None,
                   duplicate_columns=None) -> Topology:
    devices: dict[str, Device] = {}
    vlans: dict[str, Vlan] = {}
    for r in rows:
        if r.role.lower() == VLAN_ROLE:
            vlans.setdefault(r.vlan, Vlan(vid=r.vlan, name=r.name, subnet=r.address, line=r.line))
            continue
        if not r.name:
            continue
        dev = devices.setdefault(r.name, Device(name=r.name, role=r.role))
        dev.rows.append(r)

    links: list[Link] = []
    ambiguous: list = []
    seen: dict = {}
    for r in rows:
        if r.role.lower() == VLAN_ROLE or not r.connected_to or not r.name:
            continue
        local_port = r.local_port or r.interface
        key = frozenset([(r.name, local_port), (r.connected_to, r.remote_port)])
        if key in seen:
            seen[key].lines.append(r.line)
            continue
        # A reciprocal row that left remote_port blank is the same cable, not a second link.
        matches = [l for l in links
                   if _same_cable(l, r.name, local_port, r.connected_to, r.remote_port)]
        if len(matches) > 1:
            ambiguous.append((r.line, [l.id for l in matches]))
            continue  # never guess which cable this is, and never add another one
        if len(matches) == 1:
            link = matches[0]
            link.lines.append(r.line)
            local_row = r if (not r.local_port or r.local_port == r.interface or not r.interface) \
                else devices[r.name].row_for_port(local_port)
            _fill_link_end(link, r.name, local_port, r.connected_to, r.remote_port,
                           local_row, devices)
            seen[key] = link
            seen[frozenset([(link.a.device, link.a.port),
                            (link.b.device, link.b.port)])] = link
            continue
        remote_dev = devices.get(r.connected_to)
        remote_row = remote_dev.row_for_port(r.remote_port) if remote_dev else None
        local_row = r if (not r.local_port or r.local_port == r.interface or not r.interface) \
            else devices[r.name].row_for_port(local_port)
        link = Link(id=f"L{len(links) + 1}",
                    a=LinkEnd(r.name, local_port, local_row),
                    b=LinkEnd(r.connected_to, r.remote_port, remote_row),
                    lines=[r.line])
        seen[key] = link
        links.append(link)
    return Topology(rows=rows, devices=devices, vlans=vlans, links=links,
                    header_errors=header_errors or [], ambiguous=ambiguous,
                    unknown_columns=unknown_columns or [],
                    duplicate_columns=duplicate_columns or [])


def _ports_compatible(a, b):
    return (not a) or (not b) or a == b


def _same_cable(link, name, local_port, peer, remote_port):
    """True if this row is a (possibly underspecified) declaration of link."""
    if name == peer or {name, peer} != {link.a.device, link.b.device}:
        return False
    loc, rem = (link.a, link.b) if link.a.device == name else (link.b, link.a)
    return _ports_compatible(local_port, loc.port) and _ports_compatible(remote_port, rem.port)


def _fill_link_end(link, name, local_port, peer, remote_port, local_row, devices):
    """Fill a blank port or missing row from the reciprocal declaration. Never overwrites."""
    mine, theirs = (link.a, link.b) if link.a.device == name else (link.b, link.a)
    if not mine.port and local_port:
        mine.port = local_port
    if mine.row is None and local_row is not None:
        mine.row = local_row
    if not theirs.port and remote_port:
        theirs.port = remote_port
    if theirs.row is None and remote_port:
        dev = devices.get(peer)
        if dev:
            theirs.row = dev.row_for_port(remote_port)


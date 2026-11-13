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
        rows = []
        for i, raw in enumerate(reader, start=2):
            vals = {c: (raw.get(c) or "").strip() for c in COLUMNS}
            if not any(vals.values()):
                continue
            rows.append(Row(line=i, **vals))
    return build_topology(rows, header_errors)


def build_topology(rows, header_errors=None) -> Topology:
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
    seen: dict = {}
    for r in rows:
        if r.role.lower() == VLAN_ROLE or not r.connected_to or not r.name:
            continue
        local_port = r.local_port or r.interface
        key = frozenset([(r.name, local_port), (r.connected_to, r.remote_port)])
        if key in seen:
            seen[key].lines.append(r.line)
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
                    header_errors=header_errors or [])

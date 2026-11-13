"""Network validation with the standard-library ipaddress module.

Validation only reports. It never edits, renames or re-addresses anything.
"""
from __future__ import annotations

import ipaddress
from collections import defaultdict
from dataclasses import dataclass

from .model import ROLE_ALIASES, VLAN_ROLE, Topology, parse_cidr

ERROR, WARNING = "error", "warning"


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    line: int | None
    message: str

    def __str__(self):
        where = f"line {self.line}: " if self.line else ""
        return f"{self.severity.upper():7} {self.code:18} {where}{self.message}"


def validate(topo: Topology) -> list[Finding]:
    out: list[Finding] = []
    add = lambda sev, code, line, msg: out.append(Finding(sev, code, line, msg))

    for msg in topo.header_errors:
        add(ERROR, "missing-column", 1, msg)
    if topo.header_errors:
        return out

    # --- row level: required values, roles, CIDR syntax ---------------------
    roles_seen: dict[str, tuple[str, int]] = {}
    for r in topo.rows:
        if not r.name:
            add(ERROR, "missing-name", r.line, "row has no name")
        if not r.role:
            add(ERROR, "missing-role", r.line, f"'{r.name}' has no role")
        elif r.role.lower() != VLAN_ROLE and r.role.lower() not in ROLE_ALIASES:
            add(ERROR, "unknown-role", r.line,
                f"'{r.name}' has unknown role '{r.role}' (known: {', '.join(sorted(ROLE_ALIASES))}, vlan)")
        if r.role and r.name and r.role.lower() != VLAN_ROLE:
            prev = roles_seen.setdefault(r.name, (r.role.lower(), r.line))
            if prev[0] != r.role.lower():
                add(ERROR, "role-conflict", r.line,
                    f"'{r.name}' is '{r.role}' here but '{prev[0]}' on line {prev[1]}")
        if r.address:
            if r.role.lower() == VLAN_ROLE:
                try:
                    ipaddress.ip_network(r.address, strict=True)
                except ValueError as exc:
                    add(ERROR, "invalid-cidr", r.line,
                        f"VLAN {r.vlan or '?'} subnet '{r.address}' is not a valid network ({exc})")
            elif "/" not in r.address:
                add(ERROR, "invalid-cidr", r.line,
                    f"'{r.name}' address '{r.address}' has no prefix length (write it as CIDR, e.g. 10.0.0.1/24)")
            elif parse_cidr(r.address) is None:
                add(ERROR, "invalid-cidr", r.line, f"'{r.name}' address '{r.address}' is not a valid CIDR")
        if r.vlan:
            if not r.vlan.isdigit() or not 1 <= int(r.vlan) <= 4094:
                add(ERROR, "invalid-vlan", r.line, f"VLAN id '{r.vlan}' must be a number from 1 to 4094")

    # --- VLAN definitions ----------------------------------------------------
    vlan_rows = [r for r in topo.rows if r.role.lower() == VLAN_ROLE]
    seen_vid: dict[str, int] = {}
    for r in vlan_rows:
        if not r.vlan:
            add(ERROR, "invalid-vlan", r.line, f"VLAN definition '{r.name}' has no vlan id")
        elif r.vlan in seen_vid:
            add(ERROR, "duplicate-vlan", r.line, f"VLAN {r.vlan} is already defined on line {seen_vid[r.vlan]}")
        else:
            seen_vid[r.vlan] = r.line

    # --- per address checks ---------------------------------------------------
    ip_owner: dict = {}
    for r in topo.rows:
        if r.role.lower() == VLAN_ROLE:
            continue
        ip = parse_cidr(r.address)
        if r.vlan and r.vlan not in topo.vlans:
            add(ERROR, "undefined-vlan", r.line,
                f"'{r.name}' uses VLAN {r.vlan}, which has no 'vlan' definition row")
        if ip is None:
            continue
        net = ip.network
        if net.version == 4 and net.prefixlen < 31 and ip.ip in (net.network_address, net.broadcast_address):
            kind = "network" if ip.ip == net.network_address else "broadcast"
            add(ERROR, "outside-subnet", r.line,
                f"'{r.name}' {r.address} is the {kind} address of {net}, not a usable host address")
        if r.vlan and r.vlan in topo.vlans:
            vnet = topo.vlans[r.vlan].network
            if vnet is not None and (ip.ip not in vnet or ip.network != vnet):
                add(ERROR, "outside-subnet", r.line,
                    f"'{r.name}' {r.address} does not match VLAN {r.vlan} subnet {vnet}")
        key = (ip.ip,)
        port = r.interface or r.local_port
        if key in ip_owner and ip_owner[key][:2] != (r.name, port):
            other = ip_owner[key]
            add(ERROR, "duplicate-ip", r.line,
                f"{ip.ip} on '{r.name}' {port or ''} is already used by '{other[0]}' {other[1] or ''} (line {other[2]})".replace("  ", " "))
        else:
            ip_owner.setdefault(key, (r.name, port, r.line))

    # --- links -----------------------------------------------------------------
    port_use = defaultdict(list)  # (device, port) -> [link ids]
    for link in topo.links:
        line = link.lines[0]
        if link.b.device not in topo.devices:
            add(ERROR, "dangling-link", line,
                f"'{link.a.device}' connects to '{link.b.device}', which is not a device in this file")
            continue
        if link.a.device == link.b.device:
            add(WARNING, "self-link", line, f"'{link.a.device}' is connected to itself")
        for end in (link.a, link.b):
            if end.port:
                port_use[(end.device, end.port)].append(link)
        ia, ib = parse_cidr(link.a.address), parse_cidr(link.b.address)
        if ia is not None and ib is not None and ia.network != ib.network:
            add(ERROR, "outside-subnet", line,
                f"link {link.a.device} {link.a.port} ({link.a.address}) to {link.b.device} "
                f"{link.b.port} ({link.b.address}) is not in one subnet")
    for (dev, port), links in port_use.items():
        if len(links) > 1:
            others = ", ".join(f"{l.a.device}<->{l.b.device} (line {l.lines[0]})" for l in links)
            add(ERROR, "port-reused", links[1].lines[0],
                f"'{dev}' port {port} is used by {len(links)} links: {others}")

    for dev in topo.devices.values():
        if not any(r.address for r in dev.rows):
            if dev.tier != "access":
                add(WARNING, "no-address", dev.rows[0].line, f"'{dev.name}' has no IP address")

    out.sort(key=lambda f: (f.severity != ERROR, f.line or 0, f.code))
    return out


def has_errors(findings) -> bool:
    return any(f.severity == ERROR for f in findings)

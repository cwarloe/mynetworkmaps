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
        return f"{self.severity.upper():7} {self.code:22} {where}{self.message}"


def validate(topo: Topology) -> list[Finding]:
    out: list[Finding] = []
    add = lambda sev, code, line, msg: out.append(Finding(sev, code, line, msg))

    for msg in topo.header_errors:
        add(ERROR, "missing-column", 1, msg)
    for col in topo.duplicate_columns:
        add(ERROR, "duplicate-column", 1, f"column '{col}' appears more than once")
    for col in topo.unknown_columns:
        add(WARNING, "unknown-column", 1,
            f"column '{col}' is not a known field and was ignored")
    if topo.header_errors or topo.duplicate_columns:
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
                    vnet = ipaddress.ip_network(r.address, strict=True)
                except ValueError as exc:
                    add(ERROR, "invalid-cidr", r.line,
                        f"VLAN {r.vlan or '?'} subnet '{r.address}' is not a valid network ({exc})")
                else:
                    if vnet.version == 6 and vnet.prefixlen >= 96 and vnet.network_address.ipv4_mapped is not None:
                        add(ERROR, "invalid-cidr", r.line,
                            f"VLAN {r.vlan or '?'} subnet '{r.address}' is IPv4-mapped (::ffff:0:0/96); "
                            f"write the IPv4 subnet instead")
            elif "/" not in r.address:
                add(ERROR, "invalid-cidr", r.line,
                    f"'{r.name}' address '{r.address}' has no prefix length (write it as CIDR, e.g. 10.0.0.1/24)")
            elif parse_cidr(r.address) is None:
                add(ERROR, "invalid-cidr", r.line, f"'{r.name}' address '{r.address}' is not a valid CIDR")
        if any(x.strip() for x in r.extra):
            add(ERROR, "extra-fields", r.line,
                f"row has {len(r.extra)} more field(s) than the header: {r.extra!r} (quote values that contain commas)")
        if r.vlan:
            if not (r.vlan.isascii() and r.vlan.isdigit()) or not 1 <= int(r.vlan) <= 4094:
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
            add(ERROR, f"host-is-{kind}", r.line,
                f"'{r.name}' {r.address} is the {kind} address of {net}, not a usable host address")
        elif net.version == 6 and net.prefixlen < 127 and ip.ip == net.network_address:
            # RFC 4291 2.6.1 Subnet-Router anycast; RFC 6164 exempts /127
            add(WARNING, "subnet-anycast", r.line,
                f"'{r.name}' {r.address} is the Subnet-Router anycast address of {net}, not a host address")
        if ip.version == 6 and ip.ip.ipv4_mapped is not None:
            add(ERROR, "invalid-cidr", r.line,
                f"'{r.name}' {r.address} is an IPv4-mapped address (::ffff:0:0/96), which is not assigned to interfaces; "
                f"write {ip.ip.ipv4_mapped} instead")
            continue
        ll6 = ip.version == 6 and ip.ip.is_link_local
        if r.vlan and r.vlan in topo.vlans and not ll6:  # fe80::/10 sits beside the VLAN's global prefix
            vnet = topo.vlans[r.vlan].network
            if (vnet is not None and ip.version == 4 and ip.ip.is_link_local
                    and vnet.version == 4 and not vnet.is_link_local):
                # RFC 3927 1.8: link-local hosts share the link with routable ones;
                # 1.6/1.9 make a manual or DHCP 169.254 address suspect, not wrong
                add(WARNING, "link-local-in-vlan", r.line,
                    f"'{r.name}' {r.address} is IPv4 link-local (RFC 3927) on VLAN {r.vlan} ({vnet}); "
                    f"this is likely an APIPA or failed DHCP lease, and the address was not changed")
            elif vnet is not None and (ip.ip not in vnet or ip.network != vnet):
                add(ERROR, "outside-subnet", r.line,
                    f"'{r.name}' {r.address} does not match VLAN {r.vlan} subnet {vnet}")
        key = (ip.ip,)
        port = r.interface or r.local_port
        if ip.ip.is_link_local:  # fe80::/10 and 169.254/16 (RFC 3927) are link-scoped
            continue
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
        for dev_port in {(e.device, e.port) for e in (link.a, link.b) if e.port}:
            port_use[dev_port].append(link)
        ia, ib = parse_cidr(link.a.address), parse_cidr(link.b.address)
        if ia is not None and ib is not None and ia.network != ib.network:
            if ia.ip in ib.network or ib.ip in ia.network:
                add(ERROR, "link-prefix-mismatch", line,
                    f"link {link.a.device} {link.a.port} ({link.a.address}) to {link.b.device} "
                    f"{link.b.port} ({link.b.address}) ends use different prefixes "
                    f"(/{ia.network.prefixlen} vs /{ib.network.prefixlen})")
            else:
                add(ERROR, "outside-subnet", line,
                    f"link {link.a.device} {link.a.port} ({link.a.address}) to {link.b.device} "
                    f"{link.b.port} ({link.b.address}) is not in one subnet")
        for near, far in ((link.a, link.b), (link.b, link.a)):
            if far.port and far.row is None and near.address:
                add(WARNING, "link-subnet-unchecked", line,
                    f"{far.device} port {far.port} is not described in this file, so the subnet of "
                    f"{near.device} {near.port} ({near.address}) could not be checked against it")
    for (dev, port), links in port_use.items():
        if len(links) > 1:
            others = ", ".join(f"{l.a.device}<->{l.b.device} (line {l.lines[0]})" for l in links)
            add(ERROR, "port-reused", links[1].lines[0],
                f"'{dev}' port {port} is used by {len(links)} links: {others}")

    # --- link-local uniqueness per L2 segment (RFC 4291 2.5.6, RFC 4862 5.4) ----
    segs = defaultdict(set)  # id(row) -> {("link", id) | ("vlan", vid)}
    for link in topo.links:
        for near, far in ((link.a, link.b), (link.b, link.a)):
            if near.row is not None:
                segs[id(near.row)].add(("link", link.id))
                if far.row is not None and far.row.vlan and not far.row.address:
                    segs[id(near.row)].add(("vlan", far.row.vlan))  # plugged into a switch access port
                elif (far.device in topo.devices and topo.devices[far.device].tier == "access"
                      and (far.row is None or (not far.row.vlan and not far.row.address))):
                    segs[id(near.row)].add(("switch", far.device))  # untagged port, VLAN not stated
    ll_owner = {}
    for r in topo.rows:
        ip = parse_cidr(r.address)
        if r.role.lower() == VLAN_ROLE or ip is None or not ip.ip.is_link_local:
            continue
        mine = set(segs[id(r)]) | ({("vlan", r.vlan)} if r.vlan else set())
        for seg in sorted(mine):
            other = ll_owner.setdefault((ip.ip, seg), r)
            if other.name != r.name:
                where = {"vlan": f"VLAN {seg[1]}",
                         "switch": f"switch {seg[1]} (untagged ports, VLAN not stated)"}.get(seg[0], "link")
                add(WARNING if seg[0] == "switch" else ERROR, "duplicate-ip", r.line,
                    f"link-local {ip.ip} on '{r.name}' is already used by '{other.name}' "
                    f"(line {other.line}) on the same {where}")
                break

    for (line, ids) in topo.ambiguous:
        add(ERROR, "ambiguous-link", line,
            f"this row could describe any of links {', '.join(ids)}; fill in local_port and remote_port")

    for dev in topo.devices.values():
        if not any(r.address for r in dev.rows):
            if dev.tier != "access":
                add(WARNING, "no-address", dev.rows[0].line, f"'{dev.name}' has no IP address")

    out.sort(key=lambda f: (f.severity != ERROR, f.line or 0, f.code))
    return out


def has_errors(findings) -> bool:
    return any(f.severity == ERROR for f in findings)

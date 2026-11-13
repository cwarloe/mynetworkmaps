import pytest

from netdiag.model import load_csv
from netdiag.validate import ERROR, has_errors, validate

BAD = {
    "invalid_cidr.csv": {"invalid-cidr"},
    "outside_subnet.csv": {"outside-subnet", "host-is-network"},
    "duplicate_ip.csv": {"duplicate-ip"},
    "dangling_link.csv": {"dangling-link"},
    "port_reused.csv": {"port-reused"},
    "undefined_vlan.csv": {"undefined-vlan", "outside-subnet"},
    "missing_column.csv": {"missing-column"},
}


@pytest.mark.parametrize("name,codes", sorted(BAD.items()))
def test_bad_inputs_fail_with_the_right_finding(samples, name, codes):
    findings = validate(load_csv(samples / "bad" / name))
    assert has_errors(findings)
    got = {f.code for f in findings if f.severity == ERROR}
    assert got <= codes and got, got


def test_invalid_cidr_reports_both_rows(samples):
    f = [x for x in validate(load_csv(samples / "bad" / "invalid_cidr.csv")) if x.code == "invalid-cidr"]
    assert [x.line for x in f] == [2, 3]
    assert "10.10.10.300/24" in f[0].message


def test_outside_subnet_covers_vlan_link_and_network_address(samples):
    msgs = [f.message for f in validate(load_csv(samples / "bad" / "outside_subnet.csv"))]
    assert any("VLAN 10 subnet 10.10.10.0/24" in m for m in msgs)
    assert any("not in one subnet" in m for m in msgs)
    assert any("network address" in m for m in msgs)


@pytest.mark.parametrize("name", ["ten_device_tree.csv", "redundant_network.csv", "inventory_only.csv"])
def test_samples_are_valid(samples, name):
    findings = validate(load_csv(samples / name))
    assert not has_errors(findings), [str(f) for f in findings]


def test_values_are_never_rewritten(samples, tmp_path):
    p = tmp_path / "odd.csv"
    p.write_text("name,role,address\nPC-01,pc, 10.10.10.050/24 \n", encoding="utf-8")
    topo = load_csv(p)
    # leading zeros are invalid for ipaddress; we must report, not "fix" them
    assert topo.devices["PC-01"].rows[0].address == "10.10.10.050/24"
    assert any(f.code == "invalid-cidr" for f in validate(topo))


def test_links_are_never_invented(samples):
    topo = load_csv(samples / "redundant_network.csv")
    declared = set()
    for r in topo.rows:
        if r.connected_to:
            declared.add(frozenset([(r.name, r.local_port or r.interface), (r.connected_to, r.remote_port)]))
    assert len(topo.links) == len(declared) == 19


def test_reciprocal_local_port_without_interface_is_checked(tmp_path):
    p = tmp_path / "mismatch.csv"
    p.write_text(
        "name,role,address,interface,vlan,connected_to,local_port,remote_port\n"
        "A,core,10.0.0.1/30,,,B,p1,p2\n"
        "B,core,10.0.1.1/30,,,A,p2,p1\n",
        encoding="utf-8",
    )
    findings = validate(load_csv(p))
    assert any(f.code == "outside-subnet" and "not in one subnet" in f.message for f in findings)


HDR = "name,role,address,interface,vlan,connected_to,local_port,remote_port,notes"


def _load(tmp_path, name, body, header=HDR):
    p = tmp_path / name
    p.write_text(header + "\n" + body, encoding="utf-8")
    return load_csv(p)


def test_ipv6_link_local_may_repeat_on_different_links(tmp_path):
    topo = _load(tmp_path, "ll.csv",
                 "R1,edge,fe80::1/64,Gi0/1,,SW1,Gi0/1,p1,\n"
                 "SW1,access,fe80::2/64,p1,,,,,\n"
                 "R2,edge,fe80::1/64,Gi0/1,,SW2,Gi0/1,p1,\n"
                 "SW2,access,fe80::2/64,p1,,,,,\n")
    findings = validate(topo)
    assert not has_errors(findings), [str(f) for f in findings]
    assert len(topo.links) == 2


def test_reciprocal_row_with_blank_remote_port_is_one_link(tmp_path):
    topo = _load(tmp_path, "rec.csv",
                 "A,core,10.0.0.1/30,p1,,B,p1,p2,\n"
                 "B,core,10.0.0.2/30,p2,,A,p2,,\n")
    findings = validate(topo)
    assert len(topo.links) == 1
    assert topo.links[0].lines == [2, 3]
    assert not any(f.code == "port-reused" for f in findings)
    assert not has_errors(findings)


def test_ipv6_subnet_router_anycast_is_warned_except_slash_127(tmp_path):
    bad = validate(_load(tmp_path, "anycast.csv", "A,server,2001:db8:1::/64,eth0,,,,,\n"))
    assert any(f.code == "subnet-anycast" and f.severity != ERROR for f in bad)
    ok = validate(_load(tmp_path, "slash127.csv",
                        "A,core,2001:db8::/127,p1,,B,p1,p1,\n"
                        "B,core,2001:db8::1/127,p1,,,,,\n"))
    assert not ok


def test_ipv4_mapped_ipv6_is_rejected(tmp_path):
    findings = validate(_load(tmp_path, "mapped.csv",
                              "A,server,10.1.1.10/24,eth0,,,,,\n"
                              "B,server,::ffff:10.1.1.10/120,eth0,,,,,\n"))
    assert any(f.code == "invalid-cidr" and "IPv4-mapped" in f.message for f in findings)


def test_unicode_digit_vlan_is_reported_not_a_crash(tmp_path):
    findings = validate(_load(tmp_path, "vlan.csv", "A,pc,10.10.10.5/24,eth0,²,,,,\n"))
    assert any(f.code == "invalid-vlan" for f in findings)


def test_extra_csv_fields_are_reported(tmp_path):
    topo = _load(tmp_path, "extra.csv", "A,pc,10.10.10.5/24,eth0,,,,,uplink, primary\n")
    assert topo.devices["A"].rows[0].notes == "uplink"
    assert any(f.code == "extra-fields" for f in validate(topo))


def test_self_link_is_not_reported_as_port_reused(tmp_path):
    findings = validate(_load(tmp_path, "self.csv", "A,core,10.0.0.1/30,p1,,A,p1,p1,\n"))
    assert any(f.code == "self-link" for f in findings)
    assert not any(f.code == "port-reused" for f in findings)


def test_unresolved_remote_port_warns_that_subnet_was_not_checked(tmp_path):
    findings = validate(_load(tmp_path, "typo.csv",
                              "A,edge,10.0.0.1/30,p1,,B,p1,p9,\n"
                              "B,edge,10.9.9.2/30,p1,,,,,\n"))
    assert any(f.code == "link-subnet-unchecked" and f.severity != ERROR for f in findings)
    assert not has_errors(findings)


def test_host_is_network_and_link_prefix_mismatch_codes(tmp_path):
    net = validate(_load(tmp_path, "net.csv", "A,pc,10.1.1.0/24,eth0,,,,,\n"))
    assert any(f.code == "host-is-network" and "network address" in f.message for f in net)
    bc = validate(_load(tmp_path, "bc.csv", "A,pc,10.1.1.255/24,eth0,,,,,\n"))
    assert any(f.code == "host-is-broadcast" and "broadcast address" in f.message for f in bc)
    mismatch = validate(_load(tmp_path, "pfx.csv",
                              "A,edge,10.0.0.1/30,p1,,B,p1,p1,\n"
                              "B,edge,10.0.0.2/24,p1,,,,,\n"))
    assert any(f.code == "link-prefix-mismatch" and "different prefixes" in f.message for f in mismatch)


def test_link_local_duplicate_on_a_shared_vlan_is_reported(tmp_path):
    findings = validate(_load(
        tmp_path, "llseg.csv",
        "Users,vlan,10.10.10.0/24,,10,,,,\n"
        "SW1,access,10.10.10.2/24,Vlan10,10,,,,\n"
        "SW1,access,,p1,10,,,,\n"
        "SW1,access,,p2,10,,,,\n"
        "R1,edge,fe80::1/64,Gi0/1,,SW1,Gi0/1,p1,\n"
        "R2,edge,fe80::1/64,Gi0/1,,SW1,Gi0/1,p2,\n",
    ))
    dups = [f for f in findings if f.code == "duplicate-ip"]
    assert any(f.line == 7 for f in dups)
    assert any("VLAN 10" in f.message for f in dups)


def test_link_local_on_a_vlan_interface_is_not_outside_the_global_prefix(tmp_path):
    findings = validate(_load(
        tmp_path, "llvlan.csv",
        "Users,vlan,2001:db8:10::/64,,10,,,,\n"
        "R1,edge,2001:db8:10::1/64,Vlan10,10,,,,\n"
        "R1,edge,fe80::1/64,Vlan10,10,,,,\n",
    ))
    assert not has_errors(findings), [str(f) for f in findings]
    assert not any(f.code == "outside-subnet" for f in findings)


def test_ambiguous_reciprocal_row_is_reported_not_turned_into_a_link(tmp_path):
    topo = _load(
        tmp_path, "amb.csv",
        "A,core,,p1,,B,p1,,\n"
        "A,core,,p2,,B,p2,,\n"
        "B,core,,p7,,A,p7,,\n",
    )
    assert len(topo.links) == 2
    findings = validate(topo)
    assert any(f.code == "ambiguous-link" and f.line == 4 for f in findings)


def test_ipv4_mapped_vlan_subnet_is_rejected(tmp_path):
    findings = validate(_load(tmp_path, "vmap.csv", "Users,vlan,::ffff:10.10.10.0/120,,10,,,,\n"))
    assert any(f.code == "invalid-cidr" and "IPv4-mapped" in f.message for f in findings)


def test_empty_trailing_field_is_not_extra_fields(tmp_path):
    findings = validate(_load(tmp_path, "trail.csv", "PC,pc,10.10.10.5/24,eth0,,,,,,\n"))
    assert not any(f.code == "extra-fields" for f in findings)
    assert not has_errors(findings)


def test_unknown_header_column_is_warned(tmp_path):
    topo = _load(tmp_path, "site.csv", "PC,pc,10.10.10.5/24,Boise\n",
                 header="name,role,address,site")
    findings = validate(topo)
    assert any(f.code == "unknown-column" and "site" in f.message and f.severity != ERROR
               for f in findings)
    assert not has_errors(findings)
    assert topo.devices["PC"].rows[0].address == "10.10.10.5/24"


def test_ipv4_link_local_may_repeat_on_different_ha_pairs(tmp_path):
    findings = validate(_load(
        tmp_path, "ha2.csv",
        "FW-1A,firewall,169.254.1.1/30,eth3,,FW-1B,eth3,eth3,\n"
        "FW-1B,firewall,169.254.1.2/30,eth3,,,,,\n"
        "FW-2A,firewall,169.254.1.1/30,eth3,,FW-2B,eth3,eth3,\n"
        "FW-2B,firewall,169.254.1.2/30,eth3,,,,,\n",
    ))
    assert not has_errors(findings), [str(f) for f in findings]
    assert not any(f.code == "duplicate-ip" for f in findings)


def test_one_ha_pair_with_ipv4_link_local_is_clean(tmp_path):
    findings = validate(_load(
        tmp_path, "ha1.csv",
        "FW-1A,firewall,169.254.1.1/30,eth3,,FW-1B,eth3,eth3,\n"
        "FW-1B,firewall,169.254.1.2/30,eth3,,,,,\n",
    ))
    assert not findings


def test_duplicate_header_column_is_reported(tmp_path):
    topo = _load(tmp_path, "dupcol.csv", "PC,pc,10.10.10.5/24,10.10.10.6/24\n",
                 header="name,role,address,address")
    findings = validate(topo)
    assert any(f.code == "duplicate-column" and "address" in f.message for f in findings)
    assert not any(f.code == "missing-column" for f in findings)


def test_value_under_a_blank_header_is_reported(tmp_path):
    findings = validate(_load(
        tmp_path, "blank.csv", "PC,pc,10.10.10.5/24,lostvalue\n",
        header="name,role,address,",
    ))
    assert any(f.code == "extra-fields" and "lostvalue" in f.message for f in findings)


def test_link_local_on_untagged_switch_ports_is_a_warning(tmp_path):
    findings = validate(_load(
        tmp_path, "untagged.csv",
        "SW1,access,,p1,,,,,\n"
        "SW1,access,,p2,,,,,\n"
        "R1,edge,fe80::1/64,Gi0/1,,SW1,Gi0/1,p1,\n"
        "R2,edge,fe80::1/64,Gi0/1,,SW1,Gi0/1,p2,\n",
    ))
    dups = [f for f in findings if f.code == "duplicate-ip"]
    assert dups and all(f.severity != ERROR for f in dups)
    assert not has_errors(findings)


def test_ipv4_link_local_on_a_routable_vlan_is_a_warning(tmp_path):
    findings = validate(_load(
        tmp_path, "apipa.csv",
        "Users,vlan,10.10.10.0/24,,10,,,,\n"
        "PC,pc,169.254.1.10/16,eth0,10,,,,\n",
    ))
    hits = [f for f in findings if f.code == "link-local-in-vlan"]
    assert hits and all(f.severity != ERROR for f in hits)
    assert "was not changed" in hits[0].message
    assert not any(f.code == "outside-subnet" for f in findings)
    assert not has_errors(findings)


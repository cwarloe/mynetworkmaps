import pytest

from netdiag.model import load_csv
from netdiag.validate import ERROR, has_errors, validate

BAD = {
    "invalid_cidr.csv": {"invalid-cidr"},
    "outside_subnet.csv": {"outside-subnet"},
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

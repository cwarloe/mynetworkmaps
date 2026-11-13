import pytest

from netdiag.geometry import check, is_clean, summary
from netdiag.layout import layout
from netdiag.model import load_csv
from netdiag.render_svg import render_svg

SAMPLES = ["ten_device_tree.csv", "redundant_network.csv", "inventory_only.csv"]


@pytest.mark.parametrize("name", SAMPLES)
def test_samples_have_zero_overlaps(samples, name):
    res = check(layout(load_csv(samples / name)))
    assert is_clean(res), summary(res)


def test_redundant_crossings_are_the_minimum_for_dual_homing(samples):
    # 3 access switches each dual-homed to 2 distribution switches is K(2,3):
    # any two-row drawing has at least 3 crossings.
    assert check(layout(load_csv(samples / "redundant_network.csv")))["edge_crossings"] == 3


@pytest.mark.parametrize("name", SAMPLES)
def test_layout_is_deterministic(samples, name):
    a = render_svg(layout(load_csv(samples / name), "x"))
    b = render_svg(layout(load_csv(samples / name), "x"))
    assert a == b


@pytest.mark.parametrize("name", SAMPLES[:2])
def test_every_link_drawn_once_and_orthogonal(samples, name):
    topo = load_csv(samples / name)
    scene = layout(topo)
    assert sorted(e.id for e in scene.edges) == sorted(l.id for l in topo.links)
    for e in scene.edges:
        for (x0, y0), (x1, y1) in zip(e.points, e.points[1:]):
            assert abs(x0 - x1) < 0.01 or abs(y0 - y1) < 0.01, e.id


def test_port_labels_show_exact_input_addresses(samples):
    topo = load_csv(samples / "redundant_network.csv")
    scene = layout(topo)
    shown = {ln.text for l in scene.labels if l.kind == "port" for ln in l.lines}
    for link in topo.links:
        for end in (link.a, link.b):
            if end.address:
                assert end.address in shown


def test_role_rows_go_top_to_bottom(samples):
    scene = layout(load_csv(samples / "ten_device_tree.csv"))
    y = {n.id: n.rect.y for n in scene.nodes}
    assert y["EDGE-01"] < y["FW-01"] < y["CORE-01"] < y["DIST-01"] < y["ACCESS-01"] < y["PC-01"]
    assert y["DIST-01"] == y["DIST-02"]


def test_ha_pair_and_cross_link_are_side_by_side(samples):
    scene = layout(load_csv(samples / "redundant_network.csv"))
    peers = [e for e in scene.edges if e.kind == "peer"]
    assert len(peers) == 2
    for e in peers:
        assert len(e.points) == 2 and e.points[0][1] == e.points[1][1]


def test_reciprocal_local_port_labels_show_both_addresses(tmp_path):
    p = tmp_path / "pair.csv"
    p.write_text(
        "name,role,address,interface,vlan,connected_to,local_port,remote_port\n"
        "A,core,10.0.0.1/30,,,B,p1,p2\n"
        "B,core,10.0.0.2/30,,,A,p2,p1\n",
        encoding="utf-8",
    )
    topo = load_csv(p)
    assert len(topo.links) == 1
    assert {topo.links[0].a.address, topo.links[0].b.address} == {"10.0.0.1/30", "10.0.0.2/30"}
    shown = {ln.text for lab in layout(topo).labels if lab.kind == "port" for ln in lab.lines}
    assert "10.0.0.1/30" in shown and "10.0.0.2/30" in shown


def test_inventory_mixed_ipv4_ipv6_lays_out(tmp_path):
    p = tmp_path / "mixed.csv"
    p.write_text("name,role,address\nPC-V4,pc,10.0.0.1/24\nPC-V6,pc,2001:db8::1/64\n",
                 encoding="utf-8")
    scene = layout(load_csv(p))
    assert {n.id for n in scene.nodes} == {"PC-V4", "PC-V6"}


def test_parallel_same_row_links_are_drawn_apart(tmp_path):
    p = tmp_path / "parallel.csv"
    p.write_text(
        "name,role,address,interface,vlan,connected_to,local_port,remote_port\n"
        "CORE-01,core,10.0.0.1/30,p1,,CORE-02,p1,p1\n"
        "CORE-01,core,10.0.0.5/30,p2,,CORE-02,p2,p2\n"
        "CORE-02,core,10.0.0.2/30,p1,,,\n"
        "CORE-02,core,10.0.0.6/30,p2,,,\n",
        encoding="utf-8",
    )
    topo = load_csv(p)
    scene = layout(topo)
    peers = [e for e in scene.edges]
    assert len(peers) == 2
    assert abs(peers[0].points[0][1] - peers[1].points[0][1]) > 1
    assert is_clean(check(scene)), summary(check(scene))
    shown = {ln.text for lab in scene.labels if lab.kind == "port" for ln in lab.lines}
    assert {"p1", "p2", "10.0.0.1/30", "10.0.0.2/30", "10.0.0.5/30", "10.0.0.6/30"} <= shown


def test_svi_address_is_shown_on_the_device_not_the_trunk(samples):
    topo = load_csv(samples / "redundant_network.csv")
    trunks = [l for l in topo.links if l.a.port == "Gi1/0/49" or l.b.port == "Gi1/0/49"]
    assert len(trunks) == 3
    for l in trunks:
        assert not l.a.address and not l.b.address
    scene = layout(topo)
    shown = {ln.text for lab in scene.labels if lab.kind == "port" for ln in lab.lines}
    assert "10.99.0.11/24" not in shown
    access = next(n for n in scene.nodes if n.id == "ACCESS-01")
    assert any("10.99.0.11/24" in ln.text for ln in access.lines)


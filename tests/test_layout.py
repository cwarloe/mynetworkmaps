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

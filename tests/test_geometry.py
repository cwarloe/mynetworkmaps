from netdiag.geometry import check, is_clean, summary
from netdiag.scene import Edge, Label, Node, Rect, Scene, TextLine


def _scene(nodes, edges, labels):
    return Scene(500, 500, nodes, edges, labels, [])


def test_checker_counts_each_overlap_kind():
    a = Node("A", Rect(0, 0, 100, 40), "pc", "#000", [])
    b = Node("B", Rect(0, 200, 100, 40), "pc", "#000", [])
    c = Node("C", Rect(200, 100, 100, 40), "pc", "#000", [])
    e1 = Edge("e1", [(50, 40), (50, 200)], "A", "B")
    e2 = Edge("e2", [(20, 120), (250, 120)], "B", "C")        # passes through C, crosses e1
    t = [TextLine("x", 10)]
    l1 = Label("l1", Rect(40, 60, 30, 20), t, "port", owner="e1")    # struck by its own line
    l2 = Label("l2", Rect(60, 70, 30, 20), t, "port", owner="e2")    # overlaps l1
    l3 = Label("l3", Rect(90, 30, 30, 20), t, "port", owner="e2")    # overlaps node A
    l4 = Label("l4", Rect(45, 150, 20, 20), t, "port", owner="e2")   # sits on e1's line
    s = summary(check(_scene([a, b, c], [e1, e2], [l1, l2, l3, l4])))
    assert s["label_label"] == 1
    assert s["label_node"] == 1
    assert s["edge_node"] == 1
    assert s["label_own_edge"] == 1
    assert s["label_edge"] == 1
    assert s["edge_crossings"] == 1


def test_clean_scene_is_clean():
    a = Node("A", Rect(0, 0, 100, 40), "pc", "#000", [])
    b = Node("B", Rect(0, 200, 100, 40), "pc", "#000", [])
    e = Edge("e", [(50, 40), (50, 200)], "A", "B")
    lab = Label("l", Rect(56, 46, 40, 20), [TextLine("x", 10)], "port", owner="e")
    assert is_clean(check(_scene([a, b], [e], [lab])))

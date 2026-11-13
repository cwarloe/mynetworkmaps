import xml.etree.ElementTree as ET

from PIL import Image

from netdiag.cli import main


def test_cli_writes_editable_drawio_svg_png_html(samples, tmp_path):
    assert main([str(samples / "redundant_network.csv"), "-o", str(tmp_path)]) == 0
    root = ET.parse(tmp_path / "redundant_network.drawio").getroot()
    devices = root.findall(".//UserObject")
    edges = [c for c in root.iter("mxCell") if c.get("edge") == "1"]
    assert len(devices) == 14
    assert len(edges) == 19
    ids = {d.get("id") for d in devices}
    for e in edges:
        assert e.get("source") in ids and e.get("target") in ids   # real connections, not loose lines
    assert not any("image=data:image/png" in (c.get("style") or "") for c in root.iter("mxCell"))
    ET.parse(tmp_path / "redundant_network.svg")
    w, h = Image.open(tmp_path / "redundant_network.png").size
    assert w > 1000 and h > 1000
    html = (tmp_path / "redundant_network.html").read_text(encoding="utf-8")
    assert "pointerdown" in html and "CORE-01" in html


def test_cli_fails_on_bad_input_and_writes_nothing(samples, tmp_path, capsys):
    assert main([str(samples / "bad" / "duplicate_ip.csv"), "-o", str(tmp_path / "o")]) == 1
    assert "duplicate-ip" in capsys.readouterr().out
    assert not (tmp_path / "o").exists()


def test_check_only(samples, tmp_path):
    assert main([str(samples / "ten_device_tree.csv"), "--check-only", "-o", str(tmp_path / "o")]) == 0
    assert not (tmp_path / "o").exists()

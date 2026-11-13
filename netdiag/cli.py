"""Command line entry point: netdiag <file.csv> [-o OUTDIR]."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .geometry import check, is_clean, summary
from .layout import layout
from .model import load_csv
from .render_drawio import render_drawio
from .render_html import render_html
from .render_png import render_png
from .render_svg import render_svg
from .validate import ERROR, has_errors, validate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="netdiag", description="Turn a device CSV into an accurate, clean "
                                 "network diagram (.drawio, .svg, .png, .html).")
    ap.add_argument("csv", help="input CSV file")
    ap.add_argument("-o", "--out", default="out", help="output folder (default: out)")
    ap.add_argument("--title", help="diagram title (default: file name)")
    ap.add_argument("--check-only", action="store_true", help="validate only, write nothing")
    ap.add_argument("--scale", type=float, default=2.0, help="PNG scale factor (default 2)")
    args = ap.parse_args(argv)

    path = Path(args.csv)
    if not path.exists():
        print(f"netdiag: file not found: {path}", file=sys.stderr)
        return 2
    topo = load_csv(path)
    findings = validate(topo)
    errors = [f for f in findings if f.severity == ERROR]
    print(f"Validated {path.name}: {len(topo.devices)} devices, {len(topo.links)} links, "
          f"{len(topo.vlans)} VLANs")
    for f in findings:
        print("  " + str(f))
    if has_errors(findings):
        print(f"FAILED: {len(errors)} error(s). Fix the CSV and run again. Nothing was drawn.")
        return 1
    print("  no errors" + (f" ({len(findings)} warning(s))" if findings else ""))
    if args.check_only:
        return 0

    scene = layout(topo, args.title or path.stem)
    res = check(scene)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    (out / f"{stem}.drawio").write_text(render_drawio(scene, args.title or stem), encoding="utf-8")
    (out / f"{stem}.svg").write_text(render_svg(scene), encoding="utf-8")
    render_png(scene, out / f"{stem}.png", scale=args.scale)
    (out / f"{stem}.html").write_text(render_html(scene, args.title or stem), encoding="utf-8")
    (out / f"{stem}.overlaps.json").write_text(json.dumps(summary(res), indent=2), encoding="utf-8")
    s = summary(res)
    print("Overlap check: " + ", ".join(f"{k}={v}" for k, v in s.items()))
    print("  clean" if is_clean(res) else "  WARNING: overlaps found, see the .overlaps.json file")
    for ext in ("drawio", "svg", "png", "html"):
        print(f"Wrote {out / (stem + '.' + ext)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

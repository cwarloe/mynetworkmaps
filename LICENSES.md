# Third-party licenses

| component | used for | license | notes |
| --- | --- | --- | --- |
| Python standard library (`ipaddress`, `csv`, `json`, `xml`) | validation, parsing, output | PSF License | ships with Python |
| [Pillow](https://python-pillow.org) | text measurement and PNG drawing | MIT-CMU (HPND style, permissive) | only runtime dependency |
| DejaVu Sans fonts (`netdiag/fonts/`) | measuring and drawing text | Bitstream Vera license, DejaVu changes public domain | full text in `netdiag/fonts/LICENSE-DejaVu.txt` |
| [pytest](https://pytest.org) | tests only | MIT | dev dependency |
| [Graphviz](https://graphviz.org) | optional comparison baseline only (`tools/graphviz_baseline.py`) | Eclipse Public License 1.0 | not imported or bundled; netdiag does not need it |

Device icons in `netdiag/style.py` are original, generic drawings made for this project. No Cisco or other
vendor stencils, logos or icon sets are included. ELK (EPL-2.0) is not used.

The draw.io output is a plain XML file; opening it in diagrams.net does not add any license terms to this
project.

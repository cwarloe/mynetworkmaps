"""Deterministic text measurement with the bundled DejaVu Sans font.

DejaVu Sans is a wide font, close to Verdana, so labels sized with it also fit
when a viewer substitutes Verdana or Arial.
"""
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).parent / "fonts"
FONT_FILES = {False: FONT_DIR / "DejaVuSans.ttf", True: FONT_DIR / "DejaVuSans-Bold.ttf"}
FONT_STACK = "DejaVu Sans, Verdana, Arial, sans-serif"
LINE_FACTOR = 1.3


@lru_cache(maxsize=None)
def font(size: float, bold: bool = False, scale: float = 1.0):
    return ImageFont.truetype(str(FONT_FILES[bold]), max(1, round(size * scale)))


@lru_cache(maxsize=None)
def text_width(text: str, size: float, bold: bool = False) -> float:
    # measure at 10x for sub-pixel accuracy
    return font(size, bold, 10.0).getlength(text) / 10.0


def line_height(size: float) -> float:
    return size * LINE_FACTOR


def block_size(lines):
    """lines: list of (text, size, bold). Returns (width, height)."""
    if not lines:
        return 0.0, 0.0
    w = max(text_width(t, s, b) for t, s, b in lines)
    h = sum(line_height(s) for _, s, _ in lines)
    return w, h

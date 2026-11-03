"""Containers for what we read from one PDF page.

This file holds shapes only, no logic. Every later step reads and writes these.

Coordinate convention (the same everywhere in this project):
  * unit: PDF points (1 point = 1/72 inch)
  * origin: top-left corner of the page
  * x grows to the right, y grows DOWNWARD
  * a box is (x0, y0, x1, y1): left, top, right, bottom
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Word:
    """One word and the rectangle it occupies."""

    text: str                  # the word, after safe cleaning
    x0: float
    y0: float
    x1: float
    y1: float
    size: float                # font size in points (used later to spot headings)
    bold: bool                 # True if the font is bold (also used for headings)
    font: str = ""             # font name as stored in the PDF (weights differ by font)
    raw: Optional[str] = None  # the original text, kept ONLY if cleaning changed it


@dataclass(frozen=True)
class Line:
    """A straight line drawn on the page (table rules, underlines, decoration)."""

    x0: float
    y0: float
    x1: float
    y1: float
    width: float               # stroke thickness in points


@dataclass(frozen=True)
class Rect:
    """A rectangle drawn on the page (shaded cells, boxes, thin rules)."""

    x0: float
    y0: float
    x1: float
    y1: float
    fill: Optional[str] = None  # fill colour as "#rrggbb", or None if not filled


@dataclass(frozen=True)
class Image:
    """The box an embedded picture occupies."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Page:
    """Everything we recorded about one page."""

    number: int                # physical page number, starting at 1
    width: float
    height: float
    rotation: int              # 0, 90, 180 or 270
    words: list[Word] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    rects: list[Rect] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)

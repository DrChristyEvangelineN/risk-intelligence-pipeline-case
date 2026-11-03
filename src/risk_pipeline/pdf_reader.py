"""Step 0: read a PDF into page models (words, drawn shapes, images, with coordinates).

This module is the ONLY place that touches the PDF library (PyMuPDF). Everything
else works on the containers in page_model.py. Swapping the library later means
rewriting this one file.

Run it:
    python -m risk_pipeline.pdf_reader <pdf> --out <json>
"""
from __future__ import annotations

import argparse
import hashlib
import math
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pymupdf

from risk_pipeline.page_model import Image, Line, Page, Rect, Word
from risk_pipeline.page_store import save_pages

SCHEMA_VERSION = 1
DECIMALS = 2  # coordinates rounded to 0.01 point (1/7200 inch): far below any layout signal

# --- Safe, mechanical cleaning (judgement calls are NOT made here) -----------------
LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
INVISIBLE = {"­": None, "​": None, "﻿": None}  # soft hyphen, zero-width space, BOM
_CLEAN_TABLE = str.maketrans({**LIGATURES, **INVISIBLE})
BOLD_WORDS = ("bold", "semibold", "black", "heavy")
TEXT_FLAGS = pymupdf.TEXTFLAGS_WORDS  # what page.get_text("words") uses


def clean_text(text: str) -> str:
    """Expand ligatures; drop invisible characters. Nothing else."""
    return text.translate(_CLEAN_TABLE)


def _r(x: float) -> float:
    return round(float(x), DECIMALS)


def _hex(colour) -> Optional[str]:
    if not colour:
        return None
    r, g, b = (max(0, min(255, round(c * 255))) for c in colour[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_bold(font: str, flags: int) -> bool:
    return bool(flags & 16) or any(k in font.lower() for k in BOLD_WORDS)


def _read_words(page: "pymupdf.Page", stats: Counter) -> list[Word]:
    """Words from PyMuPDF's own word list, enriched with font info from the same text page."""
    # One text page => word and span numbering agree. Explicit flags (not defaults) so the
    # result does not change if the library changes its default.
    tp = page.get_textpage(flags=TEXT_FLAGS)
    blocks = tp.extractDICT()["blocks"]
    spans_by_line: dict[tuple[int, int], list[dict]] = {}
    for b in blocks:
        if b.get("type") != 0:
            continue
        for li, line in enumerate(b["lines"]):
            spans_by_line[(b["number"], li)] = line["spans"]

    words: list[Word] = []
    for x0, y0, x1, y1, text, block_no, line_no, _word_no in tp.extractWORDS():
        stats["parser_words"] += 1
        cleaned = clean_text(text)
        if not cleaned:
            stats["dropped_empty_after_cleaning"] += 1
            continue
        size, font, bold = 0.0, "", False
        spans = spans_by_line.get((block_no, line_no), [])
        cx = (x0 + x1) / 2
        best = None
        for s in spans:  # a line has only a few spans
            if s["bbox"][0] - 0.5 <= cx <= s["bbox"][2] + 0.5:
                best = s
                break
        if best is None and spans:
            best = spans[0]
        if best is not None:
            size, font = float(best["size"]), best["font"]
            bold = _is_bold(font, best["flags"])
        else:
            stats["words_without_font_info"] += 1
        raw = text if cleaned != text else None
        if raw is not None:
            stats["words_changed_by_cleaning"] += 1
        words.append(Word(cleaned, _r(x0), _r(y0), _r(x1), _r(y1), _r(size), bold, font, raw))
    return words


def _read_drawings(page: "pymupdf.Page", stats: Counter) -> tuple[list[Line], list[Rect]]:
    """Vector shapes. Straight lines and rectangles are kept; curves are counted, not kept."""
    lines: list[Line] = []
    rects: list[Rect] = []
    for dr in page.get_drawings():
        width = dr.get("width") or 0.0
        fill = _hex(dr.get("fill"))
        for item in dr["items"]:
            kind = item[0]
            if kind == "l":
                a, b = item[1], item[2]
                lines.append(Line(_r(a.x), _r(a.y), _r(b.x), _r(b.y), _r(width)))
            elif kind == "re":
                r = item[1]
                rects.append(Rect(_r(r.x0), _r(r.y0), _r(r.x1), _r(r.y1), fill))
            elif kind == "qu":
                r = item[1].rect
                rects.append(Rect(_r(r.x0), _r(r.y0), _r(r.x1), _r(r.y1), fill))
            else:
                stats["curves_not_kept"] += 1
    return lines, rects


def _read_images(page: "pymupdf.Page") -> list[Image]:
    out = []
    for info in page.get_image_info():
        b = info["bbox"]
        out.append(Image(_r(b[0]), _r(b[1]), _r(b[2]), _r(b[3])))
    return out


def read_pdf(pdf_path: Path) -> tuple[list[Page], dict]:
    """Read every page. Returns (pages, stamp) where stamp records how it was made."""
    stats: Counter = Counter()
    pages: list[Page] = []
    with pymupdf.open(pdf_path) as doc:
        for index, p in enumerate(doc):
            words = _read_words(p, stats)
            lines, rects = _read_drawings(p, stats)
            pages.append(Page(
                number=index + 1, width=_r(p.rect.width), height=_r(p.rect.height),
                rotation=p.rotation, words=words, lines=lines, rects=rects,
                images=_read_images(p),
            ))
    stamp = {
        "schema_version": SCHEMA_VERSION,
        "source_file": pdf_path.name,
        "source_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "source_bytes": pdf_path.stat().st_size,
        "page_count": len(pages),
        "pymupdf_version": pymupdf.__version__,
        "python_version": platform.python_version(),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coordinate_decimals": DECIMALS,
        "stats": dict(stats),
    }
    return pages, stamp


# --- Checks ------------------------------------------------------------------------
def check_pages(pages: list[Page], pdf_path: Path, stamp: dict, tolerance: float = 1.0) -> list[str]:
    """Independent checks on the output. Returns a list of problems (empty = all good)."""
    problems: list[str] = []
    expected_emptied = stamp["stats"].get("dropped_empty_after_cleaning", 0)
    total_emptied = 0
    with pymupdf.open(pdf_path) as doc:
        if doc.page_count != len(pages):
            problems.append(f"page count: PDF has {doc.page_count}, we have {len(pages)}")
        for page, src in zip(pages, doc):
            # 1. word count must match an independent call to the parser, once we add back
            #    words that cleaning emptied (e.g. a lone soft hyphen)
            parser_n = len(src.get_text("words"))
            emptied = parser_n - len(page.words)
            total_emptied += emptied
            if emptied < 0 or any(not w.text for w in page.words):
                problems.append(f"page {page.number}: we have {len(page.words)} words, parser has {parser_n}")
            # 2. every box inside the page (small tolerance) and well-formed
            for w in page.words:
                vals = (w.x0, w.y0, w.x1, w.y1, w.size)
                if not all(math.isfinite(v) for v in vals):
                    problems.append(f"page {page.number}: non-numeric value in word {w.text!r}")
                    break
                if not (w.x0 < w.x1 and w.y0 < w.y1):
                    problems.append(f"page {page.number}: empty or inverted box for {w.text!r}")
                    break
                if (w.x0 < -tolerance or w.y0 < -tolerance
                        or w.x1 > page.width + tolerance or w.y1 > page.height + tolerance):
                    problems.append(f"page {page.number}: box outside page for {w.text!r}")
                    break
    if total_emptied != expected_emptied:
        problems.append(f"words lost: {total_emptied} missing vs {expected_emptied} emptied by cleaning")
    return problems


def low_text_pages(pages: list[Page], fraction: float = 0.15) -> list[tuple[int, int]]:
    """Pages with far fewer words than the typical page (relative to the median)."""
    median = statistics.median(len(p.words) for p in pages) if pages else 0
    return [(p.number, len(p.words)) for p in pages if len(p.words) < fraction * median]


# --- Command line ------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read a PDF into page models (Step 0).")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/intermediate/page_models.json"))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")  # never crash on a character the console lacks

    t0 = time.time()
    pages, stamp = read_pdf(args.pdf)
    t_read = time.time() - t0
    save_pages(pages, stamp, args.out)
    problems = check_pages(pages, args.pdf, stamp)

    words = sum(len(p.words) for p in pages)
    print(f"Read {len(pages)} pages in {t_read:.1f}s -> {args.out} "
          f"({args.out.stat().st_size / 1e6:.1f} MB)")
    print(f"  words={words}  lines={sum(len(p.lines) for p in pages)}  "
          f"rects={sum(len(p.rects) for p in pages)}  images={sum(len(p.images) for p in pages)}")
    print(f"  stats: {stamp['stats']}")
    low = low_text_pages(pages)
    print(f"  low-text pages (< 15% of median words): {low if low else 'none'}")
    if problems:
        print(f"CHECKS FAILED ({len(problems)}):")
        for msg in problems[:20]:
            print("  -", msg)
        return 1
    print("CHECKS PASSED: page count, word counts, box validity")
    return 0


if __name__ == "__main__":
    sys.exit(main())

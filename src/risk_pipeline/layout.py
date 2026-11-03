"""Step 1: layout analysis. Turns loose words into lines, rows, columns and cells.

Everything here works on the page model only (never on the PDF) and every threshold
is RELATIVE (to word height, page width or page count), never a fixed coordinate.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from risk_pipeline.page_model import Page, Word

# ---- parameters (all relative) -------------------------------------------------------
MARGIN_BAND = 0.12      # top/bottom share of the page height treated as margin
REPEAT_FRACTION = 0.5   # share of pages a margin line must appear on to be a header/footer
SPLIT_GAP = 1.5         # gap wider than this x word height splits a text line into segments
GUTTER_MIN = 1.5        # a white strip must be wider than this x word height to be a gutter
RULE_COVERAGE = 0.5     # a horizontal rule must cover this share of the page width
GUTTER_SHARE = 0.5      # a gutter must appear in this share of row bands to count
PARAGRAPH_GAP = 1.4     # line pitch beyond this x the normal pitch starts a new paragraph


# ---- small helpers -------------------------------------------------------------------
def median_height(words: list[Word]) -> float:
    return statistics.median(w.y1 - w.y0 for w in words) if words else 0.0


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


@dataclass
class TextLine:
    words: list[Word]

    @property
    def x0(self): return min(w.x0 for w in self.words)
    @property
    def x1(self): return max(w.x1 for w in self.words)
    @property
    def y0(self): return min(w.y0 for w in self.words)
    @property
    def y1(self): return max(w.y1 for w in self.words)
    @property
    def size(self): return max(w.size for w in self.words)
    @property
    def text(self): return " ".join(w.text for w in self.words)


def text_lines(words: list[Word], split: bool = True, split_gap: float = SPLIT_GAP) -> list[TextLine]:
    """Group words into lines by vertical overlap; optionally cut at wide gaps."""
    rows: list[list[Word]] = []
    row_box: list[list[float]] = []
    for w in sorted(words, key=lambda w: (w.y0 + w.y1) / 2):
        placed = False
        for r, box in zip(rows, row_box):
            h = min(w.y1 - w.y0, box[1] - box[0])
            if h > 0 and _overlap(w.y0, w.y1, box[0], box[1]) >= 0.5 * h:
                r.append(w)
                box[0], box[1] = min(box[0], w.y0), max(box[1], w.y1)
                placed = True
                break
        if not placed:
            rows.append([w])
            row_box.append([w.y0, w.y1])
    lines: list[TextLine] = []
    for r in rows:
        r.sort(key=lambda w: w.x0)
        if not split:
            lines.append(TextLine(r))
            continue
        h = median_height(r)
        cur = [r[0]]
        for prev, w in zip(r, r[1:]):
            if w.x0 - prev.x1 > split_gap * h:
                lines.append(TextLine(cur))
                cur = []
            cur.append(w)
        lines.append(TextLine(cur))
    lines.sort(key=lambda l: (round(l.y0, 0), l.x0))
    return lines


# ---- header / footer detection ---------------------------------------------------------
def _normalise(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip())


def margin_noise(pages: list[Page]) -> dict[int, set[Word]]:
    """Words that belong to headers/footers: margin text repeated on many pages.

    Digits are replaced by '#' so '51 | Vestas Annual Report 2025' equals the same line on
    every other page. Returns {page number: set of words to ignore}.
    """
    n = len(pages)
    per_page: dict[int, list[tuple[tuple[str, str], list[Word]]]] = {}
    counts: Counter = Counter()
    for p in pages:
        zone_words = {"top": [], "bottom": []}
        for w in p.words:
            cy = (w.y0 + w.y1) / 2
            if cy < MARGIN_BAND * p.height:
                zone_words["top"].append(w)
            elif cy > (1 - MARGIN_BAND) * p.height:
                zone_words["bottom"].append(w)
        found = []
        seen = set()
        for zone, ws in zone_words.items():
            for line in text_lines(ws):
                key = (zone, _normalise(line.text))
                found.append((key, line.words))
                seen.add(key)
        per_page[p.number] = found
        counts.update(seen)
    repeated = {k for k, c in counts.items() if c / n >= REPEAT_FRACTION}
    noise: dict[int, set[Word]] = {}
    for num, found in per_page.items():
        noise[num] = {w for key, ws in found if key in repeated for w in ws}
    return noise


# ---- rules, bands, gutters ---------------------------------------------------------------
def horizontal_rules(page: Page) -> list[float]:
    """y positions of horizontal rules that span a large share of the page width.

    A rule drawn as several touching or nearby segments counts as one if together they
    cover enough of the width.
    """
    tol = 0.003 * page.height
    segs: list[tuple[float, float, float]] = []
    for l in page.lines:
        if abs(l.y1 - l.y0) <= tol and abs(l.x1 - l.x0) > 0:
            segs.append(((l.y0 + l.y1) / 2, min(l.x0, l.x1), max(l.x0, l.x1)))
    for r in page.rects:
        if (r.y1 - r.y0) <= 0.004 * page.height and (r.x1 - r.x0) > 0:
            segs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
    segs.sort()
    groups: list[list[tuple[float, float, float]]] = []
    for s in segs:
        if groups and abs(s[0] - groups[-1][0][0]) <= tol:
            groups[-1].append(s)
        else:
            groups.append([s])
    ys = []
    for g in groups:
        iv = sorted((a, b) for _, a, b in g)
        total, cur0, cur1 = 0.0, iv[0][0], iv[0][1]
        for a, b in iv[1:]:
            if a <= cur1 + 0.02 * page.width:   # nearly touching segments are one rule
                cur1 = max(cur1, b)
            else:
                total += cur1 - cur0
                cur0, cur1 = a, b
        total += cur1 - cur0
        if total >= RULE_COVERAGE * page.width:
            ys.append(statistics.mean(y for y, _, _ in g))
    return ys


def vertical_gutters(words: list[Word], gutter_min: float) -> list[tuple[float, float]]:
    """White strips (no word at any height) between the leftmost and rightmost word."""
    if not words:
        return []
    lo = int(min(w.x0 for w in words))
    hi = int(max(w.x1 for w in words)) + 1
    covered = [False] * (hi - lo + 2)
    for w in words:
        for x in range(int(w.x0) - lo, int(w.x1) - lo + 1):
            covered[x] = True
    out, start = [], None
    for i in range(len(covered)):
        if not covered[i] and start is None:
            start = i
        elif covered[i] and start is not None:
            if i - start >= gutter_min:
                out.append((start + lo, i - 1 + lo))
            start = None
    return out


@dataclass
class Row:
    y0: float
    y1: float
    cells: list[list[Word]]


@dataclass
class Table:
    page: int
    col_edges: list[float]          # x positions that cut the page into columns
    header: list[Word]              # words above the first rule
    rows: list[Row] = field(default_factory=list)


def find_table(page: Page, noise: set[Word], use_gutters: bool = True) -> Optional[Table]:
    """Ruled-row table: horizontal rules cut rows, consistent white gutters cut columns.

    Works with or without vertical lines: columns come from words, rows from rules.
    Returns None when the page has fewer than two usable rules.
    """
    words = [w for w in page.words if w not in noise]
    rules = sorted(horizontal_rules(page))
    if len(rules) < 2 or not words:
        return None
    h = median_height(words)
    cuts = rules
    bands: list[list[Word]] = []
    edges = [-1e9] + cuts + [1e9]
    for a, b in zip(edges, edges[1:]):
        bands.append([w for w in words if a <= (w.y0 + w.y1) / 2 < b])
    header, body = bands[0], [b for b in bands[1:] if b]
    if not body:
        return None
    col_edges: list[float] = []
    if use_gutters:
        per_band = [vertical_gutters(b, GUTTER_MIN * h) for b in body]
        centres = sorted((a + b) / 2 for g in per_band for a, b in g)
        clusters: list[list[float]] = []
        for c in centres:
            if clusters and c - clusters[-1][-1] <= 2 * h:
                clusters[-1].append(c)
            else:
                clusters.append([c])
        for cl in clusters:
            if len(cl) >= max(1, GUTTER_SHARE * len(body)):
                col_edges.append(statistics.median(cl))
    table = Table(page.number, col_edges, header)
    ys = cuts
    for i, band in enumerate(bands[1:]):
        if not band:
            continue
        cells = [[] for _ in range(len(col_edges) + 1)]
        for w in band:
            cx = (w.x0 + w.x1) / 2
            idx = sum(1 for e in col_edges if cx > e)
            cells[idx].append(w)
        table.rows.append(Row(ys[i], ys[i + 1] if i + 1 < len(ys) else page.height, cells))
    return table


# ---- text reconstruction -----------------------------------------------------------------
def build_vocab(pages: list[Page]) -> Counter:
    vocab: Counter = Counter()
    for p in pages:
        for w in p.words:
            vocab[w.text.lower().strip(".,;:()\"'’")] += 1
    return vocab


def _join_lines(lines: list[str], vocab: Counter, stats: Counter) -> str:
    out = lines[0]
    for nxt in lines[1:]:
        if re.search(r"[A-Za-z]-$", out) and nxt[:1].islower():
            left = out.rsplit(" ", 1)[-1][:-1]
            right = re.split(r"\s", nxt)[0].strip(".,;:()")
            joined, hyph = (left + right).lower(), (left + "-" + right).lower()
            if vocab[joined] > 0:
                out, stats["hyphen_joined"] = out[:-1] + nxt, stats["hyphen_joined"] + 1
            elif vocab[hyph] > 0:
                out, stats["hyphen_kept"] = out + nxt, stats["hyphen_kept"] + 1
            else:
                out, stats["hyphen_ambiguous_joined"] = out[:-1] + nxt, stats["hyphen_ambiguous_joined"] + 1
        else:
            out = out + " " + nxt
    return out


def paragraphs(words: list[Word], vocab: Counter, stats: Optional[Counter] = None) -> list[str]:
    """Words of one cell/column -> paragraphs (split on larger-than-normal line gaps)."""
    stats = stats if stats is not None else Counter()
    lines = text_lines(words, split=False)
    if not lines:
        return []
    tops = [l.y0 for l in lines]
    diffs = [b - a for a, b in zip(tops, tops[1:])]
    pitch = statistics.median(diffs) if diffs else 0.0
    paras: list[list[str]] = [[lines[0].text]]
    for d, line in zip(diffs, lines[1:]):
        if pitch and d > PARAGRAPH_GAP * pitch:
            paras.append([])
        paras[-1].append(line.text)
    return [_join_lines(p, vocab, stats) for p in paras]


def cell_text(words: list[Word], vocab: Counter, stats: Optional[Counter] = None) -> str:
    return "\n".join(paragraphs(words, vocab, stats))


def heading(words: list[Word]) -> str:
    """The largest-font line among these words."""
    lines = text_lines(words)
    if not lines:
        return ""
    top = max(l.size for l in lines)
    best = [l for l in lines if l.size >= top - 0.01]
    return " ".join(l.text for l in sorted(best, key=lambda l: (l.y0, l.x0)))

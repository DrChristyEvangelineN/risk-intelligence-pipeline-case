"""Step 2: find the pages worth reading. Cheap, deterministic, recall-first.

Score = weighted count of risk-disclosure phrases, damped by page length. A page is a
candidate if its score is far above the document's typical page (z-score), so the cut-off
adapts to any report. Embeddings are the planned upgrade, not part of this CPU-only slice.
"""
from __future__ import annotations

import statistics

from risk_pipeline.page_model import Page, Word

# Structural phrases: labels that only appear where risks are laid out. Counted as-is.
STRUCTURAL = {
    "financial risks or opportunities": 3.0,
    "how we manage it": 3.0,
    "potential impact": 2.0,
    "main risks": 3.0,
    "principal risk": 3.0,
    "enterprise risk": 2.0,
}
# Generic vocabulary: damped by page length so long pages do not win by size alone.
GENERIC = {"mitigat": 1.5, "risks": 1.0, "risk": 1.0}
CUT_OFF_Z = 1.5   # chosen for recall: 1.5 finds all six core pages (2.0 missed p.71)


def score_page(page: Page, noise: set[Word]) -> float:
    words = [w.text for w in page.words if w not in noise]
    if len(words) < 30:
        return 0.0
    text = " ".join(words).lower()
    structural = sum(wt * text.count(ph) for ph, wt in STRUCTURAL.items())
    generic = sum(wt * text.count(ph) for ph, wt in GENERIC.items())
    return structural + generic / (len(words) ** 0.5)


def locate(pages: list[Page], noise: dict[int, set[Word]]) -> list[tuple[int, float]]:
    """Return (page number, score) for candidate pages, best first."""
    scores = {p.number: score_page(p, noise[p.number]) for p in pages}
    values = list(scores.values())
    mean, sd = statistics.mean(values), statistics.pstdev(values)
    cut = mean + CUT_OFF_Z * sd
    return sorted(((n, s) for n, s in scores.items() if s >= cut), key=lambda t: -t[1])

"""Steps 4-5: rule-based extraction from labelled layouts, plus grounding validation.

Rules are used because the scoped pages are labelled (column headings, row labels, fixed
table headers). Pages the rules do not recognise are reported as unhandled, never guessed.
"""
from __future__ import annotations

import difflib
import re
import statistics
from collections import Counter
from typing import Optional

from risk_pipeline import layout as L
from risk_pipeline.page_model import Page, Word
from risk_pipeline.schema import NOT_STATED, Evidence, Governance, Risk

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“‘])")
ESRS_CODE = re.compile(r"^[ESG]\d\b")
OPPORTUNITY_CUES = ("opportunit", "improves our value proposition", "well positioned")
BODIES = ("Executive Management Team", "Board of Directors", "Audit Committee", "Risk Committee")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text.replace("\n", " ")) if s.strip()]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def categorise(title: str, description: str, section: str, taxonomy: dict) -> str:
    for text in (title, description, section):
        low = text.lower()
        for rule in taxonomy["rules"]:
            if any(re.search(r"\b" + re.escape(k), low) for k in rule["keywords"]):
                return rule["category"]
    return "other"


def breadcrumb(page: Page, noise: set[Word]) -> str:
    """The section label printed at the top of the page (top margin text that is not repeated)."""
    top = [w for w in page.words if w not in noise and (w.y0 + w.y1) / 2 < L.MARGIN_BAND * page.height]
    return " ".join(l.text for l in L.text_lines(top))


def bbox_of(words: list[Word]) -> Optional[tuple[float, float, float, float]]:
    if not words:
        return None
    return (min(w.x0 for w in words), min(w.y0 for w in words),
            max(w.x1 for w in words), max(w.y1 for w in words))


def table_kind(table: L.Table, vocab: Counter) -> Optional[str]:
    labels = " ".join(L.cell_text(r.cells[0], vocab).lower() for r in table.rows if r.cells[0])
    body = " ".join(" ".join(w.text for c in r.cells for w in c).lower() for r in table.rows)
    if "description" in labels and ("how we manage" in labels or "mitigat" in labels):
        return "risk_matrix"
    if "financial risks or opportunities" in body or "financial risks or opportunities" in " ".join(w.text for w in table.header).lower():
        return "iro_table"
    return None


def extract_risk_matrix(table: L.Table, page: Page, noise: set[Word], vocab: Counter,
                        taxonomy: dict, stats: Counter, method: str) -> list[Risk]:
    """Grid with risk names as column headings and labelled rows (Description / impact / how we manage it)."""
    crumb = breadcrumb(page, noise)
    n_cols = len(table.col_edges) + 1
    titles = {}
    for c in range(1, n_cols):
        ws = [w for w in table.header if sum(1 for e in table.col_edges if (w.x0 + w.x1) / 2 > e) == c]
        titles[c] = " ".join(L.paragraphs(ws, vocab, stats)).strip()
    rows = {}
    for r in table.rows:
        label = L.cell_text(r.cells[0], vocab).lower()
        if "description" in label:
            rows["description"] = r
        elif "impact" in label:
            rows["impact"] = r
        elif "manage" in label or "mitigat" in label:
            rows["mitigation"] = r
    risks = []
    for c in range(1, n_cols):
        title = titles.get(c, "")
        if not title or "description" not in rows:
            stats["matrix_column_skipped"] += 1
            continue
        d_words = rows["description"].cells[c]
        d_paras = L.paragraphs(d_words, vocab, stats)
        d_sents = [s for p in d_paras for s in sentences(p)]
        lead = d_sents[:3]
        desc = " ".join(lead)
        ev = [Evidence(page=page.number, quote=s, bbox=bbox_of(d_words)) for s in lead]
        mitigation, stated = NOT_STATED, False
        if "mitigation" in rows and rows["mitigation"].cells[c]:
            m_words = rows["mitigation"].cells[c]
            mitigation = " ".join(L.paragraphs(m_words, vocab, stats))
            stated = True
            for s in sentences(mitigation):
                ev.append(Evidence(page=page.number, quote=s, bbox=bbox_of(m_words)))
        cat = categorise(title, desc, crumb, taxonomy)
        risks.append(Risk(
            id=f"p{page.number}-{slug(title)}", title=title, description=desc, category=cat,
            risk_type="principal_enterprise_risk", section=crumb, page=page.number,
            mitigation=mitigation, mitigation_stated=stated, evidence=ev))
    return risks


def extract_iro_table(table: L.Table, page: Page, noise: set[Word], vocab: Counter,
                      taxonomy: dict, stats: Counter, method: str) -> list[Risk]:
    """Double-materiality tables: keep only items on the financial-risk side that are risks."""
    crumb = breadcrumb(page, noise)
    fin_idx = None
    for w in table.header:
        if w.text == "Financial":
            fin_idx = sum(1 for e in table.col_edges if (w.x0 + w.x1) / 2 > e)
    if fin_idx is None:  # header of a later stacked table sits inside a row band
        for r in table.rows:
            for ci, cell in enumerate(r.cells):
                if any(w.text == "Financial" for w in cell):
                    fin_idx = ci
    if fin_idx is None:
        return []
    body_size = statistics.median(w.size for w in page.words if w not in noise)
    section = ""
    hdr = [w for w in table.header if w.size > 1.3 * body_size]
    for line in L.text_lines(hdr):
        if ESRS_CODE.match(line.text):
            section = line.text
    risks = []
    for r in table.rows:
        row_words = [w for c in r.cells for w in c]
        for line in L.text_lines([w for w in row_words if w.size > 1.3 * body_size]):
            if ESRS_CODE.match(line.text):
                section = line.text
        cell = [w for w in r.cells[fin_idx] if w.size <= 1.3 * body_size]
        text = L.cell_text(cell, vocab, stats).strip()
        if not text or text.lower().startswith(("financial risks or opportunities", "name and description", "value chain")):
            continue
        if "scored as immaterial" in text.lower():
            stats["skipped_immaterial"] += 1
            continue
        cell = [w for w in cell if w.text.strip()]
        first_font = cell[0].font
        n = 0
        while n < len(cell) and cell[n].font == first_font:
            n += 1
        # the name is the leading run in one font; it may wrap, so cut at the first line break in size/font
        name = " ".join(w.text for w in cell[:n]).strip()
        desc = L.cell_text(cell[n:], vocab, stats).replace("\n", " ").strip()
        low = (name + " " + desc).lower()
        if any(c in low for c in OPPORTUNITY_CUES) and "risk" not in low:
            stats["skipped_opportunity"] += 1
            continue
        # Every non-immaterial item in this column is a risk or an opportunity. Opportunities say so;
        # the rest are risks. The word "risk" in the text makes it 'stated', otherwise it is 'inferred'
        # (the risk/opportunity icon is not decoded in this slice).
        stated = "risk" in low
        vc = ""
        if fin_idx + 1 < len(r.cells):
            vc = L.cell_text(r.cells[fin_idx + 1], vocab).strip()
        cat = categorise(name, desc, section, taxonomy)
        risks.append(Risk(
            id=f"p{page.number}-{slug(name)}", title=name, description=desc, category=cat,
            risk_type="material_sustainability_risk",
            section=f"{crumb} / {section}".strip(" /"), page=page.number,
            mitigation=NOT_STATED, mitigation_stated=False,
            value_chain=vc or None, classification_basis="stated" if stated else "inferred",
            evidence=[Evidence(page=page.number, quote=f"{name} {desc}".strip(), bbox=bbox_of(cell))]))
    return risks


def extract_governance(page: Page, noise: set[Word], vocab: Counter, stats: Counter) -> Optional[Governance]:
    """Sentence about how often and by whom risks are reviewed (narrative page, columns by gutters)."""
    words = [w for w in page.words if w not in noise]
    if not words:
        return None
    body_h = L.median_height(words)
    gutters = L.vertical_gutters(words, 1.5 * body_h)
    edges = [(a + b) / 2 for a, b in gutters if a > page.width * 0.1 and b < page.width * 0.9]
    cols = [[] for _ in range(len(edges) + 1)]
    for w in words:
        cols[sum(1 for e in edges if (w.x0 + w.x1) / 2 > e)].append(w)
    for col in cols:
        for para in L.paragraphs(col, vocab, stats):
            for s in sentences(para):
                low = s.lower()
                if "review" in low and re.search(r"every|annual|quarter|month|times a year|per year", low) \
                        and any(b.lower() in low for b in BODIES):
                    return Governance(
                        review_frequency=s, reviewed_by=[b for b in BODIES if b.lower() in low],
                        page=page.number, evidence=Evidence(page=page.number, quote=s, bbox=bbox_of(col)))
    return None


# ---- grounding ---------------------------------------------------------------------
def normalise_for_match(text: str) -> str:
    text = re.sub(r"[‐-―\-]", "", text)
    return re.sub(r"\s+", "", text).lower()


def grounded(quote: str, page_text: str, threshold: float = 0.92) -> float:
    """Similarity (0..1) of the best match of the quote inside the page text.

    Whitespace, case and hyphens are ignored so a line-break hyphen cannot fail a real quote.
    """
    q, p = normalise_for_match(quote), normalise_for_match(page_text)
    if not q:
        return 0.0
    if q in p:
        return 1.0
    sm = difflib.SequenceMatcher(None, p, q, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / len(q)

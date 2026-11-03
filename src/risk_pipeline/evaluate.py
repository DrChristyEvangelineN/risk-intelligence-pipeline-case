"""Step 7: evaluate the pipeline against the golden set. Fails loudly on a regression.

Run:
    python -m risk_pipeline.evaluate                      # baseline
    python -m risk_pipeline.evaluate --fault no-gutters   # prove it catches a broken parser
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from risk_pipeline import pipeline as P
from risk_pipeline.enrich import summary_supported
from risk_pipeline.extract import grounded, sentences
from risk_pipeline.page_store import load_pages
from risk_pipeline.schema import DEFAULT_TAXONOMY, RiskReport, load_taxonomy, validate_report

THRESHOLDS = {
    "title_recall": 0.9,
    "title_precision": 0.9,
    "category_accuracy": 0.8,
    "mitigation_accuracy": 1.0,
    "grounding_rate": 1.0,
    "forbidden_items": 0,
    "schema_problems": 0,
    "governance_ok": 1.0,
    "description_support": 1.0,
}
TITLE_MATCH = 0.85
GROUNDED_AT = 0.95


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _match(extracted: list, golden: list[dict]) -> list[tuple[dict, Optional[object]]]:
    """Pair each golden risk with the best unused extracted risk (same page, similar title)."""
    used, pairs = set(), []
    for g in golden:
        best, best_s = None, 0.0
        for i, r in enumerate(extracted):
            if i in used or r.page != g["page"]:
                continue
            s = _similar(r.title, g["title"])
            if s > best_s:
                best, best_s = i, s
        if best is not None and best_s >= TITLE_MATCH:
            used.add(best)
            pairs.append((g, extracted[best]))
        else:
            pairs.append((g, None))
    return pairs


def evaluate(report: RiskReport, golden: dict, pages_by_number: dict, taxonomy: dict) -> dict:
    risks = report.risks
    pairs = _match(risks, golden["risks"])
    matched = [(g, r) for g, r in pairs if r is not None]
    n_gold, n_ext = len(golden["risks"]), len(risks)
    recall = len(matched) / n_gold if n_gold else 1.0
    precision = len(matched) / n_ext if n_ext else 0.0
    cat_ok = sum(1 for g, r in matched if r.category == g["category"])
    mit_ok = 0
    for g, r in matched:
        if g["mitigation_stated"] != r.mitigation_stated:
            continue
        if g["mitigation_stated"] and grounded(g["mitigation_quote"], r.mitigation) < GROUNDED_AT:
            continue
        mit_ok += 1
    # grounding: every sentence we output must be found on its source page
    total, found, ungrounded = 0, 0, []
    for r in risks:
        page = pages_by_number.get(r.page)
        text = " ".join(w.text for w in page.words) if page else ""
        # an extractive description must be found word-for-word on the page; a model-written one cannot be,
        # so it is held to the "adds nothing beyond its source" check below instead
        parts = (sentences(r.description) if r.description_source == "extractive" else []) \
            + (sentences(r.mitigation) if r.mitigation_stated else [])
        for s in parts:
            total += 1
            if grounded(s, text) >= GROUNDED_AT:
                found += 1
            else:
                ungrounded.append(f"{r.id}: {s[:70]}")
    written = [r for r in risks if r.description_source == "model"]
    supported = sum(1 for r in written if summary_supported(r.description, r.source_text or " ".join(w.text for w in pages_by_number[r.page].words))[0])
    forbidden = [f for f in golden["must_not_extract"]
                 if any(r.page == f["page"] and _similar(r.title, f["title"]) >= TITLE_MATCH for r in risks)]
    gov = golden["governance"]
    gov_ok = float(bool(report.governance) and gov["phrase"] in report.governance.review_frequency
                   and sorted(report.governance.reviewed_by) == sorted(gov["reviewed_by"]))
    problems = validate_report(report, taxonomy)
    metrics = {
        "title_recall": round(recall, 3),
        "title_precision": round(precision, 3),
        "category_accuracy": round(cat_ok / len(matched), 3) if matched else 0.0,
        "mitigation_accuracy": round(mit_ok / len(matched), 3) if matched else 0.0,
        "grounding_rate": round(found / total, 3) if total else 0.0,
        "forbidden_items": len(forbidden),
        "schema_problems": len(problems),
        "governance_ok": gov_ok,
        "description_support": round(supported / len(written), 3) if written else 1.0,
    }
    failed = []
    for k, v in metrics.items():
        limit = THRESHOLDS[k]
        bad = v > limit if k in ("forbidden_items", "schema_problems") else v < limit
        if bad:
            failed.append(k)
    return {
        "metrics": metrics, "thresholds": THRESHOLDS, "failed": failed, "passed": not failed,
        "details": {
            "missing": [g["title"] for g, r in pairs if r is None],
            "category_mismatches": [f"{r.id}: got {r.category}, want {g['category']}" for g, r in matched if r.category != g["category"]],
            "ungrounded_sentences": ungrounded[:10],
            "forbidden_extracted": [f["title"] for f in forbidden],
            "validation_problems": problems,
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the pipeline against the golden set.")
    ap.add_argument("--pages", type=Path, default=Path("data/intermediate/page_models.json"))
    ap.add_argument("--golden", type=Path, default=Path("eval/golden.json"))
    ap.add_argument("--fault", choices=P.FAULTS, default="none")
    P.add_llm_arguments(ap)
    ap.add_argument("--save", type=Path, default=None, help="write the scorecard as JSON")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")  # never crash on a character the console lacks

    pages, stamp = load_pages(args.pages)
    taxonomy = load_taxonomy(DEFAULT_TAXONOMY)
    scope = json.loads(P.DEFAULT_SCOPE.read_text(encoding="utf-8"))
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    try:
        model = P.build_model(args)
    except P.ModelUnavailable as e:
        print("MODEL NOT AVAILABLE:", e)
        return 2
    report = P.run(pages, stamp, taxonomy, scope, fault=args.fault, model=model, queue=[])
    result = evaluate(report, golden, {p.number: p for p in pages}, taxonomy)

    print(f"Evaluation (fault injected: {args.fault}; language model: {model.name if model else 'none'})")
    for k, v in result["metrics"].items():
        limit = THRESHOLDS[k]
        op = "<=" if k in ("forbidden_items", "schema_problems") else ">="
        mark = "FAIL" if k in result["failed"] else "ok  "
        print(f"  [{mark}] {k:22s} {v:<6} (need {op} {limit})")
    for name, items in result["details"].items():
        if items:
            print(f"  {name}:")
            for it in items:
                print(f"    - {it}")
    print("RESULT:", "PASS" if result["passed"] else f"FAIL ({', '.join(result['failed'])})")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fault": args.fault, "language_model": model.name if model else None, "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "pipeline_version": P.PIPELINE_VERSION, "taxonomy_version": taxonomy["version"],
                   "source_sha256": stamp["source_sha256"], **result}
        args.save.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

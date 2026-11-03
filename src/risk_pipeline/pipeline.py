"""Steps 2-6 wired together: locate -> layout -> extract -> validate -> structured JSON.

Run:
    python -m risk_pipeline.pipeline --pages data/intermediate/page_models.json --out output/vestas_risks.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

from risk_pipeline import extract as X
from risk_pipeline import layout as L
from risk_pipeline import locator
from risk_pipeline.page_model import Page
from risk_pipeline.page_store import load_pages
from risk_pipeline.schema import (DEFAULT_TAXONOMY, NOT_STATED, RiskReport,
                                  load_taxonomy, validate_report)

PIPELINE_VERSION = "0.1.0"
DEFAULT_SCOPE = Path(__file__).resolve().parents[2] / "config" / "scope.json"
FAULTS = ("none", "no-gutters", "hallucinate-mitigation", "taxonomy-drift")


def run(pages: list[Page], stamp: dict, taxonomy: dict, scope: dict,
        company: str = "Vestas", fault: str = "none") -> RiskReport:
    noise = L.margin_noise(pages)
    vocab = L.build_vocab(pages)
    by_number = {p.number: p for p in pages}
    candidates = locator.locate(pages, noise)
    allowed = set(scope["core_pages"]) | set(scope.get("optional_pages", []))
    target = sorted(n for n, _ in candidates if n in allowed)
    stats: Counter = Counter()
    risks, governance, unhandled = [], None, []
    for n in target:
        page = by_number[n]
        if governance is None:
            governance = X.extract_governance(page, noise[n], vocab, stats)
        table = L.find_table(page, noise[n], use_gutters=(fault != "no-gutters"))
        kind = X.table_kind(table, vocab) if table else None
        if kind == "risk_matrix":
            risks += X.extract_risk_matrix(table, page, noise[n], vocab, taxonomy, stats, "rules")
        elif kind == "iro_table":
            risks += X.extract_iro_table(table, page, noise[n], vocab, taxonomy, stats, "rules")
        elif not (governance and governance.page == n):
            unhandled.append(n)
    if fault == "hallucinate-mitigation":
        for r in risks:
            if r.mitigation_stated:
                r.mitigation = "Vestas relies on insurance and contractual penalties to cover losses."
                break
    if fault == "taxonomy-drift" and risks:
        risks[0].category = "cybersecurity"
    report = RiskReport(
        company=company, source_file=stamp["source_file"], source_sha256=stamp["source_sha256"],
        pipeline_version=PIPELINE_VERSION, taxonomy_version=taxonomy["version"],
        extraction_method="rules (layout geometry); no LLM in this slice",
        risks=risks, governance=governance,
        coverage={
            "locator_candidates": [n for n, _ in candidates],
            "processed_pages": target,
            "candidates_outside_scope": [n for n, _ in candidates if n not in allowed],
            "pages_without_a_handler": unhandled,
            "stats": dict(stats),
            "fault_injected": fault,
        })
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Extract structured risks from page models.")
    ap.add_argument("--pages", type=Path, default=Path("data/intermediate/page_models.json"))
    ap.add_argument("--out", type=Path, default=Path("output/vestas_risks.json"))
    ap.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    ap.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    ap.add_argument("--company", default="Vestas")
    ap.add_argument("--fault", choices=FAULTS, default="none", help="inject a failure (for the eval demo)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")  # never crash on a character the console lacks

    pages, stamp = load_pages(args.pages)
    taxonomy = load_taxonomy(args.taxonomy)
    scope = json.loads(args.scope.read_text(encoding="utf-8"))
    report = run(pages, stamp, taxonomy, scope, args.company, args.fault)
    problems = validate_report(report, taxonomy)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"{len(report.risks)} risks, governance={'yes' if report.governance else 'no'} -> {args.out}")
    print(f"  processed pages: {report.coverage['processed_pages']}")
    print(f"  candidates outside scope (not processed): {report.coverage['candidates_outside_scope']}")
    print(f"  pages without a handler: {report.coverage['pages_without_a_handler']}")
    print(f"  stats: {report.coverage['stats']}")
    if problems:
        print("VALIDATION PROBLEMS:")
        for p in problems:
            print("  -", p)
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

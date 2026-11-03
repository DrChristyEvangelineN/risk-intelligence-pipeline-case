"""Check the golden set against the ORIGINAL PDF text.

This deliberately does not use our layout code, so a mistake in the pipeline cannot also
hide a mistake in the answer key. It proves every golden title and quote really is on the
page it names. It cannot judge whether a category label is right: that is a human decision.

Run:
    python -m risk_pipeline.verify_golden data\\raw\\VestasAnnualReport2025.pdf
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

import pymupdf

LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
                           "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"})


def norm(text: str) -> str:
    """Lowercase letters and digits only: ignores spaces, hyphens, punctuation, line breaks."""
    return re.sub(r"[\W_]+", "", text.translate(LIGATURES).lower())


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Verify the golden set against the original PDF.")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--golden", type=Path, default=Path("eval/golden.json"))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    bad = 0
    with pymupdf.open(args.pdf) as doc:
        text = {n: norm(doc[n - 1].get_text("text")) for n in
                {g["page"] for g in golden["risks"] + golden["must_not_extract"]} | {golden["governance"]["page"]}}

        def check(label: str, page: int, needle: str) -> None:
            nonlocal bad
            ok = norm(needle) in text[page]
            bad += 0 if ok else 1
            print(f"  [{'ok  ' if ok else 'FAIL'}] p.{page}  {label}: {needle[:60]}")

        print("Risks (title on page, and mitigation quote where stated):")
        for g in golden["risks"]:
            check("title", g["page"], g["title"])
            if g.get("mitigation_quote"):
                check("mitigation quote", g["page"], g["mitigation_quote"])
        print("Items that must NOT be extracted (must exist on the page, or the exclusion means nothing):")
        for f in golden["must_not_extract"]:
            check("exists", f["page"], f["title"])
        print("Governance:")
        check("phrase", golden["governance"]["page"], golden["governance"]["phrase"])
    print("RESULT:", "ALL GOLDEN TEXT FOUND IN THE PDF" if not bad else f"{bad} PROBLEM(S): fix golden.json")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

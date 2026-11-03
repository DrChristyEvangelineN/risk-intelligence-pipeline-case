"""Human-in-the-loop: turn a filled-in review queue into golden-set updates.

The pipeline writes output/review_queue.json: risks that neither the rules nor the language model could
categorise. A person opens it, fills `human_category` for each item, and then runs:

    python -m risk_pipeline.review --queue output/review_queue.json --golden eval/golden.json

For each item with a human_category:
  - a name from the taxonomy       -> the risk is added to (or corrected in) the golden set, so every future
                                      evaluation checks that decision;
  - NEW:<category name>            -> not added to the golden set (the schema only allows listed categories);
                                      written to config/taxonomy_proposals.json for the next taxonomy version.
Nothing is changed unless --apply is passed; without it the script only reports what it would do.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from risk_pipeline.schema import DEFAULT_TAXONOMY, load_taxonomy

PROPOSALS = Path(__file__).resolve().parents[2] / "config" / "taxonomy_proposals.json"


def plan(queue: dict, golden: dict, taxonomy: dict) -> dict:
    allowed = set(taxonomy["categories"])
    actions = {"add": [], "correct": [], "propose": [], "skip": [], "invalid": []}
    for item in queue["items"]:
        choice = (item.get("human_category") or "").strip()
        if item.get("applied") or not choice:
            actions["skip"].append(item["id"])
        elif choice.upper().startswith("NEW:"):
            actions["propose"].append((item, choice[4:].strip().lower().replace(" ", "_")))
        elif choice not in allowed:
            actions["invalid"].append(f"{item['id']}: {choice!r} is not in taxonomy {taxonomy['version']} (use NEW:<name> to propose one)")
        else:
            existing = next((g for g in golden["risks"] if g["page"] == item["page"] and g["title"].lower() == item["title"].lower()), None)
            actions["correct" if existing else "add"].append((item, choice, existing))
    return actions


def apply(queue: dict, golden: dict, actions: dict) -> None:
    for item, choice, existing in actions["correct"]:
        existing["category"] = choice
        existing["category_source"] = "human_review"
        item["applied"] = True
    for item, choice, _ in actions["add"]:
        entry = {"title": item["title"], "page": item["page"], "category": choice, "risk_type": item["risk_type"],
                 "mitigation_stated": bool(item.get("mitigation_stated")), "category_source": "human_review"}
        if entry["mitigation_stated"]:
            entry["mitigation_quote"] = item["mitigation"]   # a reviewer must confirm this wording against the PDF
        golden["risks"].append(entry)
        item["applied"] = True
    if actions["propose"]:
        data = json.loads(PROPOSALS.read_text(encoding="utf-8")) if PROPOSALS.exists() else {"proposals": []}
        for item, name in actions["propose"]:
            data["proposals"].append({"proposed_category": name, "risk_id": item["id"], "page": item["page"], "title": item["title"], "text": item["text"]})
            item["applied"] = True
        PROPOSALS.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Apply human category decisions to the golden set.")
    ap.add_argument("--queue", type=Path, default=Path("output/review_queue.json"))
    ap.add_argument("--golden", type=Path, default=Path("eval/golden.json"))
    ap.add_argument("--apply", action="store_true", help="write the changes (default: only report)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    actions = plan(queue, golden, load_taxonomy(DEFAULT_TAXONOMY))
    print(f"to add to golden: {len(actions['add'])} | to correct: {len(actions['correct'])} | "
          f"new categories proposed: {len(actions['propose'])} | waiting for a human: {len(actions['skip'])}")
    for problem in actions["invalid"]:
        print("  INVALID:", problem)
    if not args.apply:
        print("(dry run - add --apply to write the changes)")
        return 1 if actions["invalid"] else 0
    apply(queue, golden, actions)
    args.golden.write_text(json.dumps(golden, indent=2, ensure_ascii=False), encoding="utf-8")
    args.queue.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    print("golden set and queue updated. Re-run:  python -m risk_pipeline.evaluate")
    return 1 if actions["invalid"] else 0


if __name__ == "__main__":
    sys.exit(main())

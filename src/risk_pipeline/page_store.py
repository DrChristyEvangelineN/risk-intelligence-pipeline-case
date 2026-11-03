"""Save and load page models as JSON. Knows our containers, not the PDF library."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from risk_pipeline.page_model import Image, Line, Page, Rect, Word


def save_pages(pages: list[Page], stamp: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stamp": stamp, "pages": [asdict(p) for p in pages]}
    out_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def load_pages(path: Path) -> tuple[list[Page], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = []
    for d in data["pages"]:
        pages.append(Page(
            number=d["number"], width=d["width"], height=d["height"], rotation=d["rotation"],
            words=[Word(**w) for w in d["words"]],
            lines=[Line(**x) for x in d["lines"]],
            rects=[Rect(**x) for x in d["rects"]],
            images=[Image(**x) for x in d["images"]],
        ))
    return pages, data["stamp"]

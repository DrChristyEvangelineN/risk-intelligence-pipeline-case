"""Step 3: the output schema (Pydantic) and its validation rules."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

DEFAULT_TAXONOMY = Path(__file__).resolve().parents[2] / "config" / "taxonomy.json"
NOT_STATED = "not stated"


def load_taxonomy(path: Path = DEFAULT_TAXONOMY) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Evidence(BaseModel):
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    bbox: Optional[tuple[float, float, float, float]] = None


class Risk(BaseModel):
    id: str
    title: str = Field(min_length=3)
    description: str = Field(min_length=10)
    category: str
    risk_type: Literal["principal_enterprise_risk", "material_sustainability_risk"]
    section: str
    page: int = Field(ge=1)
    mitigation: str
    mitigation_stated: bool
    value_chain: Optional[str] = None
    classification_basis: Literal["stated", "inferred"] = "stated"
    # Where each judged field came from, so an analyst can see what a person, a rule or a model decided.
    category_source: Literal["rules", "model", "human"] = "rules"
    description_source: Literal["extractive", "model"] = "extractive"
    mitigation_source: Literal["table", "model", "none"] = "none"
    evidence: list[Evidence] = Field(min_length=1)
    # Working text for the optional language-model step. Never written to the output JSON.
    source_text: str = Field(default="", exclude=True)   # the risk's description text (what a summary reads)
    scan_text: str = Field(default="", exclude=True)     # the risk's whole own text (where mitigation is looked for)

    @field_validator("title")
    @classmethod
    def title_is_short(cls, v: str) -> str:
        if len(v.split()) > 12:
            raise ValueError("title longer than 12 words")
        return v


class Governance(BaseModel):
    review_frequency: str
    reviewed_by: list[str]
    page: int = Field(ge=1)
    evidence: Evidence


class RiskReport(BaseModel):
    company: str
    source_file: str
    source_sha256: str
    pipeline_version: str
    taxonomy_version: str
    extraction_method: str
    risks: list[Risk]
    governance: Optional[Governance] = None
    coverage: dict


def validate_report(report: RiskReport, taxonomy: dict) -> list[str]:
    """Rules beyond the type checks. Returns a list of problems (empty = valid)."""
    problems = []
    allowed = set(taxonomy["categories"])
    ids = set()
    for r in report.risks:
        if r.category not in allowed:
            problems.append(f"{r.id}: category {r.category!r} is not in taxonomy {taxonomy['version']}")
        if r.id in ids:
            problems.append(f"{r.id}: duplicate id")
        ids.add(r.id)
        if r.mitigation_stated == (r.mitigation == NOT_STATED):
            problems.append(f"{r.id}: mitigation_stated disagrees with mitigation text")
    if report.taxonomy_version != taxonomy["version"]:
        problems.append("taxonomy_version differs from the taxonomy file")
    return problems

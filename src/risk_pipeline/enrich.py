"""Optional step: use a language model where the rules are brittle - and check everything it says.

Rule of this module: THE MODEL PROPOSES, CODE VERIFIES. Nothing the model returns is trusted until a
check in this file accepts it. When a check fails, we keep what the rules produced.

Three jobs, in this order, for each risk the rules found:

1. CATEGORY  (only if the rules ended at "other")
     model must answer with a category from the closed list in taxonomy.json and not be unsure.
     otherwise the risk stays "other" and goes to the human review queue.
2. DESCRIPTION (every risk)
     model writes 2-3 sentences from the risk's text. `summary_supported` checks the summary adds no
     number, name or negation that is not in the source. If it fails, the lead-3 sentences are kept.
3. MITIGATION (every risk)
     model looks for a described action in ANY wording (manage, reduce, control...) and must COPY an
     exact sentence. `grounded` must find that sentence in the risk's own text. If a table already gave
     the mitigation (page 51), the table stays the authority and we only record whether the model agreed.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Optional

from risk_pipeline.extract import grounded, sentences
from risk_pipeline.llm import LanguageModel
from risk_pipeline.schema import NOT_STATED, Evidence, Risk

MAX_TEXT_CHARS = 2500          # keeps prompts small enough for a 3B model on a laptop
MITIGATION_GROUNDED_AT = 0.95  # same bar the evaluator uses
CONTENT_COVERAGE = 0.80        # share of a summary's longer words that must appear in the source
AGENT = re.compile(r"\b(we|our|vestas|the company)\b", re.I)
ACTION_CUES = ("manag", "mitigat", "reduc", "control", "prevent", "monitor", "address", "ensur", "implement", "hedg",
               "safeguard", "avoid", "minimi", "limit", "complian", "train", "audit", "insur", "diversif", "invest",
               "engag", "aim to", "work to", "respond")
NEGATIONS = ("not", "no", "never", "without", "cannot", "none")

CATEGORY_SYSTEM = (
    "You classify one company risk into exactly one category from a closed list. "
    "Use only the definitions given. If none fits, answer \"other\". "
    "Reply with JSON only: {\"category\": \"<name>\", \"confidence\": \"high|medium|low\", \"reason\": \"<max 20 words>\"}")
SUMMARY_SYSTEM = (
    "You summarise a company risk in 2 to 3 sentences. Use ONLY facts stated in the text. "
    "Do not add any number, name, date or fact that is not in the text. Do not give opinions. "
    "Reply with JSON only: {\"summary\": \"<2-3 sentences>\"}")
MITIGATION_SYSTEM = (
    "Decide whether the text describes an ACTION the company takes to manage, reduce, control, prevent, "
    "mitigate or respond to the risk, in ANY wording. Sentences that only describe the risk or its impact "
    "do not count. If there is such an action, copy the EXACT sentence from the text, unchanged (one or two sentences). "
    "Never rewrite or invent. Reply with JSON only: {\"mitigation_present\": true|false, \"quote\": \"<exact sentence>\"|null}")


# ---- small helpers -------------------------------------------------------------------
def parse_json(reply: str) -> Optional[dict]:
    """Models sometimes wrap JSON in extra words. Take the first {...} block; None if unusable."""
    match = re.search(r"\{.*\}", reply or "", re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def describes_company_action(sentence: str) -> bool:
    """True if the sentence names the company (we/our/Vestas) AND contains an action word.

    Needed because "copied exactly from the text" only proves the model did not invent a sentence; it does
    not prove the sentence is a mitigation. A sentence describing the risk's IMPACT is also in the text.
    Trade-off: a mitigation written in the passive ("Controls are in place") is missed.
    """
    low = sentence.lower()
    return bool(AGENT.search(sentence)) and any(c in low for c in ACTION_CUES)


def _ask(model: LanguageModel, system: str, task: str, title: str, text: str, extra: str, stats: Counter) -> Optional[dict]:
    user = f"TASK: {task}\n{extra}TITLE: {title}\nTEXT: {text[:MAX_TEXT_CHARS]}"
    stats[f"model_calls_{task}"] += 1
    try:
        obj = parse_json(model.complete(system, user))
    except Exception as e:  # a timeout or server error must never crash the run
        stats["model_errors"] += 1
        stats[f"model_error_{type(e).__name__}"] += 1
        return None
    if obj is None:
        stats["model_bad_json"] += 1
    return obj


_WORD = re.compile(r"[A-Za-z]{5,}")
_NUMBER = re.compile(r"\d[\d.,]*\d|\d")


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".,") for n in _NUMBER.findall(text)}


def summary_supported(summary: str, source: str) -> tuple[bool, list[str]]:
    """Cheap, strict checks that a summary does not go beyond its source. Returns (ok, reasons).

    This is a safety net, not proof of a good summary: a paraphrase can still shift meaning.
    """
    reasons = []
    n_sent = len(sentences(summary))
    if not 1 <= n_sent <= 3:
        reasons.append(f"sentences: {n_sent} sentences (want 1-3)")
    new_numbers = _numbers(summary) - _numbers(source)
    if new_numbers:
        reasons.append(f"numbers: not in source {sorted(new_numbers)}")
    src_low = source.lower()
    names = {w for s in sentences(summary) for w in re.findall(r"(?<!^)(?<![.!?] )\b[A-Z][a-z]{2,}\b", s)}
    new_names = {n for n in names if n.lower() not in src_low}
    if new_names:
        reasons.append(f"names: not in source {sorted(new_names)}")
    src_words = set(re.findall(r"[a-z]+", src_low))
    new_neg = [w for w in NEGATIONS if re.search(rf"\b{w}\b", summary.lower()) and w not in src_words]
    if new_neg:
        reasons.append(f"negation: not in source {new_neg}")
    stems = {w.lower()[:5] for w in src_words if len(w) >= 5}
    words = [w.lower()[:5] for w in _WORD.findall(summary)]
    if words:
        coverage = sum(1 for w in words if w in stems) / len(words)
        if coverage < CONTENT_COVERAGE:
            reasons.append(f"wording: only {coverage:.0%} of longer words appear in source (need {CONTENT_COVERAGE:.0%})")
    return (not reasons), reasons


# ---- the three jobs ------------------------------------------------------------------
def classify(risk: Risk, taxonomy: dict, model: LanguageModel, stats: Counter) -> Optional[dict]:
    """Returns the model's accepted answer {category, confidence, reason}, or None if not accepted."""
    allowed = [c for c in taxonomy["categories"] if c != "other"]
    defs = taxonomy.get("definitions", {})
    listing = "".join(f"- {c}: {defs.get(c, '')}\n" for c in allowed)
    extra = (f"CATEGORIES (choose one of these names, or other):\n{listing}"
             f"SECTION OF THE REPORT (a strong hint about the topic): {risk.section}\n")
    obj = _ask(model, CATEGORY_SYSTEM, "category", risk.title, risk.source_text or risk.description, extra, stats)
    if not obj:
        return None
    category = str(obj.get("category", "")).strip().lower()
    confidence = str(obj.get("confidence", "")).strip().lower()
    if category not in allowed:
        stats["category_rejected_not_in_list" if category != "other" else "category_model_said_other"] += 1
        return {"category": "other", "confidence": confidence, "reason": str(obj.get("reason", ""))}
    if confidence not in ("high", "medium"):
        stats["category_rejected_low_confidence"] += 1
        return {"category": "other", "confidence": confidence, "reason": str(obj.get("reason", ""))}
    return {"category": category, "confidence": confidence, "reason": str(obj.get("reason", ""))}


def enrich_risks(risks: list[Risk], taxonomy: dict, model: LanguageModel, stats: Counter,
                 queue: list[dict], guards: bool = True, rejections: Optional[list] = None) -> None:
    """Edits `risks` in place. `guards=False` exists only so tests can prove the guards matter."""
    rejections = rejections if rejections is not None else []
    for r in risks:
        # 1. category - only when the rules gave up
        if r.category == "other":
            answer = classify(r, taxonomy, model, stats)
            if answer and answer["category"] != "other":
                r.category, r.category_source = answer["category"], "model"
                stats["category_by_model"] += 1
            else:
                stats["sent_to_review"] += 1
                queue.append({
                    "id": r.id, "title": r.title, "page": r.page, "risk_type": r.risk_type,
                    "text": (r.source_text or r.description)[:1500],
                    "rules_category": "other",
                    "model_category": (answer or {}).get("category"),
                    "model_confidence": (answer or {}).get("confidence"),
                    "model_reason": (answer or {}).get("reason"),
                    "mitigation_stated": r.mitigation_stated, "mitigation": r.mitigation,
                    "human_category": None, "human_note": None, "applied": False})

        # 2. description
        obj = _ask(model, SUMMARY_SYSTEM, "summary", r.title, r.source_text or r.description, "", stats)
        summary = str(obj.get("summary", "")).strip() if obj else ""
        if summary:
            ok, reasons = summary_supported(summary, r.source_text or r.description)
            if ok or not guards:
                r.description, r.description_source = summary, "model"
                stats["summary_by_model"] += 1
            else:
                stats["summary_rejected"] += 1
                for reason in reasons:
                    stats["summary_rejected_" + reason.split(":")[0]] += 1
                rejections.append({"id": r.id, "check": "summary", "reasons": reasons, "model_said": summary})

        # 3. mitigation
        obj = _ask(model, MITIGATION_SYSTEM, "mitigation", r.title, r.scan_text or r.description, "", stats)
        quote = str(obj.get("quote") or "").strip() if obj and obj.get("mitigation_present") else ""
        verified = bool(quote) and grounded(quote, r.scan_text) >= MITIGATION_GROUNDED_AT
        if quote and not verified:
            stats["mitigation_rejected_not_in_text"] += 1
            rejections.append({"id": r.id, "check": "mitigation", "reasons": ["not found word-for-word in the risk's text"], "model_said": quote})
        elif verified and guards and not describes_company_action(quote):
            verified = False
            stats["mitigation_rejected_not_an_action"] += 1
            rejections.append({"id": r.id, "check": "mitigation", "reasons": ["found in the text, but it names no company action (describes the risk or its impact)"], "model_said": quote})
        if r.mitigation_source == "table":
            stats["mitigation_model_agrees_with_table" if verified else "mitigation_model_disagrees_with_table"] += 1
        elif verified or (quote and not guards):
            r.mitigation, r.mitigation_stated, r.mitigation_source = quote, True, "model"
            r.evidence.append(Evidence(page=r.page, quote=quote, bbox=r.evidence[0].bbox))
            stats["mitigation_found_by_model"] += 1
        else:
            r.mitigation, r.mitigation_stated, r.mitigation_source = NOT_STATED, False, "none"

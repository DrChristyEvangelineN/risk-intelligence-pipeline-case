"""Tests for the optional language-model step. Run:  python -m unittest discover -s tests -v

They use the fake StubModel, so they need no download and no internet. They prove the GUARDRAILS work,
not that a real model is good - that is what `python -m risk_pipeline.evaluate --llm ollama` measures.
"""
import json
import unittest
from collections import Counter

from risk_pipeline import enrich, review
from risk_pipeline.llm import StubModel
from risk_pipeline.schema import Evidence, Risk, load_taxonomy

TAXONOMY = load_taxonomy()
SOURCE = ("Ransomware could stop our factories. Customers may delay orders. "
          "We reduce exposure through network segmentation and regular backups.")


def make_risk(category="other", source=SOURCE, title="Digital disruption"):
    return Risk(id="p1-x", title=title, description=source[:40] + "...", category=category,
                risk_type="principal_enterprise_risk", section="s", page=1, mitigation="not stated",
                mitigation_stated=False, evidence=[Evidence(page=1, quote="q")],
                source_text=source, scan_text=source)


class FixedModel:
    """Returns whatever JSON we hand it, to simulate a misbehaving model."""
    name = "fixed"
    def __init__(self, **by_task): self.by_task = by_task
    def complete(self, system, user):
        task = user.split("TASK:")[1].split()[0]
        return self.by_task.get(task, "{}")


class CategoryTests(unittest.TestCase):
    def run_one(self, model, category="other"):
        stats, queue, r = Counter(), [], make_risk(category)
        enrich.enrich_risks([r], TAXONOMY, model, stats, queue)
        return r, stats, queue

    def test_model_assigns_listed_category(self):
        r, stats, queue = self.run_one(StubModel())
        self.assertEqual((r.category, r.category_source), ("cyber", "model"))
        self.assertEqual(queue, [])

    def test_category_outside_list_is_rejected_and_queued(self):
        bad = FixedModel(category=json.dumps({"category": "cybersecurity", "confidence": "high"}))
        r, stats, queue = self.run_one(bad)
        self.assertEqual(r.category, "other")
        self.assertEqual(len(queue), 1)

    def test_low_confidence_goes_to_review(self):
        unsure = FixedModel(category=json.dumps({"category": "cyber", "confidence": "low"}))
        r, stats, queue = self.run_one(unsure)
        self.assertEqual((r.category, len(queue)), ("other", 1))

    def test_unparseable_reply_goes_to_review(self):
        r, stats, queue = self.run_one(FixedModel(category="sorry, I cannot help"))
        self.assertEqual((r.category, len(queue)), ("other", 1))
        self.assertEqual(stats["model_bad_json"], 1)

    def test_prompt_contains_section_and_definitions(self):
        seen = []
        class Spy:
            name = "spy"
            def complete(self, system, user):
                seen.append(user)
                return "{}"
        r = make_risk("other")
        r.section = "General information / E1 Climate Change"
        enrich.enrich_risks([r], TAXONOMY, Spy(), Counter(), [])
        category_prompt = next(u for u in seen if u.startswith("TASK: category"))
        self.assertIn("E1 Climate Change", category_prompt)
        

    def test_rule_category_is_never_overridden(self):
        r, stats, queue = self.run_one(StubModel(), category="market")
        self.assertEqual((r.category, r.category_source), ("market", "rules"))


class SummaryTests(unittest.TestCase):
    def test_invented_summary_is_rejected_and_lead3_kept(self):
        r = make_risk("cyber")
        before = r.description
        stats = Counter()
        enrich.enrich_risks([r], TAXONOMY, StubModel("invent"), stats, [])
        self.assertEqual((r.description, r.description_source), (before, "extractive"))
        self.assertEqual(stats["summary_rejected"], 1)

    def test_supported_summary_is_accepted(self):
        ok, reasons = enrich.summary_supported("Ransomware could stop our factories.", SOURCE)
        self.assertTrue(ok, reasons)

    def test_new_number_new_name_and_new_negation_fail(self):
        for bad in ("Ransomware cost 40 million.", "Ransomware hit Siemens factories.", "Ransomware will never stop our factories."):
            self.assertFalse(enrich.summary_supported(bad, SOURCE)[0], bad)


class MitigationTests(unittest.TestCase):
    def test_exact_sentence_in_any_wording_is_accepted(self):
        r = make_risk("cyber")
        enrich.enrich_risks([r], TAXONOMY, StubModel(), Counter(), [])
        self.assertEqual((r.mitigation_stated, r.mitigation_source), (True, "model"))
        self.assertIn("network segmentation", r.mitigation)

    def test_invented_mitigation_is_rejected(self):
        r = make_risk("cyber")
        stats = Counter()
        enrich.enrich_risks([r], TAXONOMY, StubModel("invent"), stats, [])
        self.assertEqual((r.mitigation_stated, r.mitigation), (False, "not stated"))
        self.assertEqual(stats["mitigation_rejected_not_in_text"], 1)

    def test_table_mitigation_is_never_overwritten(self):
        r = make_risk("cyber")
        r.mitigation, r.mitigation_stated, r.mitigation_source = "From the table cell.", True, "table"
        enrich.enrich_risks([r], TAXONOMY, StubModel(), Counter(), [])
        self.assertEqual((r.mitigation, r.mitigation_source), ("From the table cell.", "table"))

    def test_sentence_from_the_text_that_is_only_an_impact_is_rejected(self):
        """The real-model failure found on p.71: a verbatim sentence that describes impact, not an action."""
        impact = "High carbon taxes increase the price of steel, increasing the overall cost to produce turbines."
        r = make_risk("climate", source="Carbon taxes. " + impact)
        fixed = FixedModel(mitigation=json.dumps({"mitigation_present": True, "quote": impact}))
        stats, rej = Counter(), []
        enrich.enrich_risks([r], TAXONOMY, fixed, stats, [], rejections=rej)
        self.assertEqual((r.mitigation_stated, r.mitigation), (False, "not stated"))
        self.assertEqual(stats["mitigation_rejected_not_an_action"], 1)
        self.assertIn("impact", rej[0]["reasons"][0])

    def test_guards_off_lets_invention_through(self):
        """Proves the guards are what stops it (the check this module exists for)."""
        r = make_risk("cyber")
        enrich.enrich_risks([r], TAXONOMY, StubModel("invent"), Counter(), [], guards=False)
        self.assertEqual(r.description_source, "model")
        self.assertIn("4.2 billion", r.description)


class ReviewTests(unittest.TestCase):
    def test_plan_adds_corrects_proposes_and_flags_invalid(self):
        golden = {"risks": [{"title": "Old", "page": 5, "category": "other", "mitigation_stated": False}]}
        item = lambda i, t, p, c: {"id": i, "title": t, "page": p, "risk_type": "principal_enterprise_risk",
                                    "text": "x", "human_category": c, "applied": False, "mitigation_stated": False, "mitigation": "not stated"}
        queue = {"items": [item("a", "New risk", 9, "cyber"), item("b", "Old", 5, "market"),
                           item("c", "Odd", 7, "NEW:Talent shortage"), item("d", "Bad", 8, "cybersecurity"), item("e", "Wait", 3, None)]}
        actions = review.plan(queue, golden, TAXONOMY)
        self.assertEqual([len(actions[k]) for k in ("add", "correct", "propose", "invalid", "skip")], [1, 1, 1, 1, 1])
        self.assertEqual(actions["propose"][0][1], "talent_shortage")


if __name__ == "__main__":
    unittest.main()

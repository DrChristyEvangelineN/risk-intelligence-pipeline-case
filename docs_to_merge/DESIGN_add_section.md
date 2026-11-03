PASTE this section into DESIGN.md just before '## Trade-offs traced to PLAN.md'.
Also: in the 'Rules first' bullet add: 'An optional language-model step (--llm ollama, the default; `--llm none` runs rules only) handles what rules handle badly; see the next section.'
Also: in the Evaluation table add a row for `rules-gap`: 'every keyword rule removed, so all risks come out as other | FAIL (category accuracy 0.0) | with the fake model fallback on the same run PASSES (eval/runs/rules_gap_recovered_with_stub_model.json)'.

---

## Language-model step (`enrich.py`; the default setup)

| Job | When it runs | What the model may do | What code checks before accepting |
|---|---|---|---|
| Category | Only when the keyword rules end at `other` | Pick one category from the closed list | Name is in the list and confidence is not low; otherwise it stays `other` and goes to `output/review_queue.json` |
| Description | Every risk | Write 2-3 sentences from the risk's own text | No number, name or negation absent from the source; 1-3 sentences; most longer words present in the source; otherwise lead-3 is kept |
| Mitigation | Every risk | Copy an exact sentence describing an action, in any wording | Sentence must be found in the risk's own text (same grounding test as the evaluator); table-derived mitigation (p.51) is never overwritten, only compared |

Each field records its origin (`category_source`, `description_source`, `mitigation_source`), so an analyst can see what a rule, a model or a person decided. Items the model also cannot place go to a review queue; `review.py` turns a person's decisions into golden-set rows or taxonomy proposals (taxonomy v2). The model runs locally through Ollama (nothing leaves the machine; temperature 0 and a fixed seed, but results can still differ slightly across machines and Ollama versions) behind a one-method interface, so it can be swapped for a hosted or bank-approved model. Limits: the guards catch invention and out-of-list answers, not a plausible but wrong category chosen with confidence; rule categories are not second-checked; checks on summaries are heuristics and a paraphrase can still shift meaning; the golden set has no reference summaries, so summary *quality* is not measured.


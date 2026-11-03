# STRETCH: what I would build next (one more week)

1. **LLM adapter for pages with no handler** (p.118 cyber narrative, climate p.85-92): temperature 0, JSON schema output, validated by the same grounding and schema checks, model version stamped, promoted only if it passes the golden set.
2. **Decode the risk/opportunity icon** from the legend geometry instead of relying on wording.
3. **Embedding locator and a bake-off** (keywords vs embeddings vs hybrid), measured on a labelled page set larger than the brief's own pages.
4. **Merge the same risk across sections** (cyber on p.51 and p.74) with a link between the records.
5. **Year-over-year trends and "newly elevated" risks:** stable risk ids across years, taxonomy v2 workflow from reviewed "other" items.
6. **Database, API and alerting layer** for analysts (deferred in PLAN.md).
7. **Better golden set:** several annotators, agreement scores, more reports and layout families.
8. **Scans and odd layouts:** OCR tier and a layout-model tier behind the same page model.
9. **CI regression gate:** run the eval on every change to parser, prompt, model or dependency.

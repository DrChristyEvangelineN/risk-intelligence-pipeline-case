\# STRETCH: what I would build next



1\. \*\*Extend the language-model step to pages with no handler\*\* : temperature 0, JSON output, validated by the same grounding and schema checks, model version stamped, promoted only if it passes the golden set. (Category, description and mitigation already use the model, behind code checks.)

2\. \*\*Decode the risk/opportunity icon\*\* from the legend geometry instead of relying on wording.

3\. \*\*Embedding locator and a bake-off\*\* (keywords vs embeddings vs hybrid), measured on a labelled page set larger than the brief's own pages.

4\. \*\*Merge the same risk across sections\*\*  with a link between the records.

5\. \*\*Year-over-year trends and "newly elevated" risks:\*\* stable risk ids across years, taxonomy v2 workflow from reviewed "other" items.

6\. \*\*Database, API and alerting layer\*\* for analysts (deferred in PLAN.md).

7\. \*\*Better golden set:\*\* several annotators, agreement scores, more reports and layout families, and human-written reference summaries so summary quality can be scored (today only invention is checked, not quality).

8\. \*\*Scans and odd layouts:\*\* OCR tier and a layout-model tier (for example a document-AI service) behind the same page model.

9\. \*\*CI regression gate:\*\* run the eval on every change to parser, prompt, model or dependency.

10\. \*\*Second-check rule categories with the model:\*\* rules can be confidently wrong when a later keyword matches; today the model is only asked when the rules give up.

11\. \*\*Stronger category model or worked examples:\*\* the 3B model reads "cost" wording as financial (injuries, carbon taxes) when rules are removed; try a larger model and few-shot examples, and measure on a larger golden set.

12\. \*\*Mitigation in passive wording:\*\* the company-action check misses forms like "Controls are in place"; a model-based action check, measured against labelled sentences, could replace the word list.


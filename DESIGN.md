\# DESIGN



One report in, structured and traceable risks out. Built to the priorities in `PLAN.md`: \*\*coverage, then correctness, then cost\*\*, with a faithfulness floor (nothing is output that cannot be found on its source page, and model output is accepted only after code checks it).



\## What was built



| Stage | Module | What it does |

|---|---|---|

| 0 Read | `pdf\_reader.py`, `page\_model.py`, `page\_store.py` | PyMuPDF (pinned `<2`) turns each page into words with boxes, font size and name, plus drawn lines, rectangles and image boxes. Saved as JSON with a stamp (file hash, library versions). Lossless apart from safe cleaning (ligatures, invisible characters). |

| 1 Layout | `layout.py` | Header and footer removal (margin text repeated on at least half the pages), hyphen joining using the document's own vocabulary, rows from horizontal rules, columns from white gutters that run the full height of a row. Every threshold is relative (word height, page width, page count). |

| 2 Locate | `locator.py` | Weighted risk-disclosure phrases plus a z-score cut-off. Finds all six core pages; recall-first. |

| 3 Schema | `schema.py`, `config/taxonomy.json` | Pydantic models; closed, versioned category list with definitions. |

| 4 Extract | `extract.py` | Rules on labelled layouts: risk matrix (p.51), double-materiality tables (p.71-74), governance sentence (p.50). |

| 5 Enrich | `enrich.py`, `llm.py`, `review.py` | Local language model for category fallback, description and mitigation, every answer checked in code; unplaced risks go to a human review queue. |

| 6 Validate | `schema.py`, `extract.py`, `enrich.py` | Types, category in list, no duplicate ids, grounding of every output sentence, checks on model output. |

| 7 Output | `pipeline.py` | `output/vestas\_risks.json`: each risk has page, section, quotes with boxes, mitigation or "not stated", classification basis, and the origin of each judged field. |

| 8 Eval | `evaluate.py`, `eval/golden.json`, `tests/` | Golden set plus evaluators that fail loudly; unit tests for the guardrails. |



\## Decomposition: why these cuts



\- \*\*Parsing is separated from extraction.\*\* The PDF library is used in one module; later stages only see our page model, so the parser can be swapped (licence, quality, or a document-AI service) without touching them, and every stage can be tested on its own.

\- \*\*Geometry before language.\*\* Columns and tables are found from word positions, not assumed. That is what lets the same code handle tables with and without ruling lines, and it avoids the column mix-up that plain text extraction produces on p.51.

\- \*\*Rules first, model where rules are brittle.\*\* The scoped pages are labelled (column headings, row labels, fixed table headers), so rules are exact, free and repeatable. The model handles what rules handle badly (a category the keywords miss, a summary, a mitigation in unexpected wording) under one principle: \*\*the model proposes, code verifies.\*\* Pages with no handler (for example the p.118 narrative) are listed in `coverage`, never guessed.

\- \*\*Guardrails in code, not in the prompt.\*\* A prompt such as "do not invent facts" is a request, not a guarantee. Checks in code (category must be in the list, mitigation must be found word for word, summaries may not add numbers, names or negations) reject bad answers whatever the model does, and can be unit-tested.



\## The language-model step (`enrich.py`)



| Job | When it runs | What the model may do | What code checks before accepting | Fallback if rejected |

|---|---|---|---|---|

| Category | Only when the keyword rules end at `other` | Pick one category from the closed list; it sees the title, text and report section | Name is in the list and confidence is not low | Stays `other`, goes to `output/review\_queue.json` |

| Description | Every risk | Write 2-3 sentences from the risk's own text | 1-3 sentences; no new number, name or negation; at least 70% of longer words found in the source | First three source sentences (lead-3), copied word for word |

| Mitigation | Every risk | Copy an exact sentence describing a company action, in any wording | Sentence found word for word in the risk's text, and names the company plus an action word | `not stated`. Where a table gives the mitigation (p.51), the table is kept and the model's answer is only compared |



Each judged field records its origin (`category\_source`, `description\_source`, `mitigation\_source`) and `coverage.model\_rejections` records every rejected answer with the reason. \*\*Human in the loop:\*\* risks the rules and the model both cannot place are queued; `review.py` turns a person's decisions into golden-set rows or taxonomy proposals (taxonomy v2).



\*\*Model choice:\*\* a 3B instruction model (`qwen2.5:3b`) run locally through Ollama, behind a one-method interface (`llm.py`), so nothing leaves the machine and it can be swapped for a hosted or bank-approved model. Temperature 0 and a fixed seed give the most repeatable behaviour available, but output can still differ slightly across machines and Ollama versions. The model's licence has not been reviewed; that is a required step before any commercial use.



\## Trade-offs traced to PLAN.md



| PLAN.md choice | Decision | Cost of the decision |

|---|---|---|

| Coverage first | Locator cut-off tuned for recall; unhandled pages reported | Some candidates are not processed (p.77, 78, 162, 118) |

| Then correctness | Grounding gate, golden set, closed taxonomy, code checks on model output, "not stated" instead of invention | Rejected model answers fall back to less polished text |

| Then cost | Rules first (free, seconds); local model for the rest | A 3B model is less accurate than a large hosted one; the model step adds minutes of local compute |

| Analyst-facing, queryable | JSON with provenance and taxonomy version | No database or API yet (deferred in PLAN.md) |

| Risks to the company only | Impacts, opportunities and items scored immaterial are excluded and counted | The risk/opportunity icon is not decoded; wording is used (`classification\_basis` says stated or inferred) |



\## Scaling to many reports (assumptions, not measurements)



\- \*\*Latency and throughput:\*\* reading 195 pages took about 3.5 s here; the rules path for 200 reports per quarter is minutes of CPU. The model step is the slow part (minutes per report on a laptop CPU); at scale it moves to a GPU service or a hosted endpoint inside the company's cloud tenant.

\- \*\*Cost:\*\* the rules path uses no tokens. If a hosted model handled only candidate pages at roughly 560 tokens per page and 15 to 20 pages per report, that is about 10k tokens per report, about 2M tokens per quarter for 200 reports, against about 20M if whole reports were sent.

\- \*\*The real scale problem is layout variety and trust.\*\* Each new layout family needs a handler or the model path, a golden set, and review. Unplaced items go to a queue; the closed taxonomy grows through reviewed "other" items (taxonomy v2) without re-reading PDFs.

\- \*\*Operations:\*\* pinned dependencies, outputs stamped with pipeline, taxonomy and library versions, the model name recorded in each run, and the eval as a gate before any parser, model or prompt change.



\## Evaluation and what it caught



`python -m risk\_pipeline.evaluate` scores recall and precision of risk titles, category accuracy, mitigation correctness, grounding, forbidden items (opportunities, impacts), schema validity, the governance field and description support. Saved runs in `eval/runs/`:



| Run | Result | Caught by |

|---|---|---|

| baseline (rules only) | PASS | |

| with model (`with\_ollama\_qwen2.5-3b`) | PASS | |

| `no-gutters` (layout broken) | FAIL, recall 0 | recall, precision, grounding |

| `hallucinate-mitigation` (stand-in for a weaker model inventing text) | FAIL | grounding, mitigation accuracy |

| `taxonomy-drift` (category outside the list) | FAIL | schema validation only (category accuracy stays above its threshold), which is why the evaluators are layered |

| `rules-gap` (every keyword rule removed, rules only) | FAIL, category accuracy 0.0 | category accuracy |

| `rules-gap` with the fake model (`rules\_gap\_recovered\_with\_stub\_model`) | PASS | shows the fallback path works end to end |



\*\*What the real model run caught.\*\* The first evaluation with the real model failed `mitigation\_accuracy` (0.9): for p.71 \*Carbon taxes and tariffs\* the model returned a sentence that is in the text but describes the risk's impact, not a company action. It was grounded, so the grounding check could not catch it. A second check (the sentence must name the company and an action) fixed it, and a unit test now reproduces the case. Lesson: a grounded answer can still be the wrong answer. This check was added after seeing the failure, on a 10-risk golden set, so its good score is partly fitted to that data.



\*\*Category fallback stress test\*\* (all keyword rules removed so the model must categorise every risk; category accuracy, need 0.8):



| Version of the category prompt | Accuracy | Misses |

|---|---|---|

| Title and text only | 0.8 | carbon taxes, injuries |

| Plus report section and a rewritten `financial` definition | 0.6 | carbon taxes, injuries, project execution, fines |

| \*\*Plus report section only (kept)\*\* | 0.8 | project execution, injuries |



The section hint fixed the climate item because the section names it (E1 Climate Change); my rewritten definition made things worse and was reverted. With 10 risks one item is 10 points, so these differences are small, and I stopped tuning rather than fit the prompt to the golden set. The 3B model reads "cost" wording as financial; this is why rules run first.



\## What changed from PLAN.md



1\. \*\*The language model is a fallback and enrichment step, not the extractor.\*\* Rules run first and every model output is checked in code.

2\. \*\*A closed category list with an `other` bucket and a human review queue\*\* instead of open-ended tags, to keep categories consistent across reports.

3\. \*\*A keyword and structure locator instead of embeddings\*\* for finding risk pages: simpler and measurable. Its cut-off was tuned on this one report, so its recall here is optimistic. An embedding bake-off is in STRETCH.



\## Known limits



\- The golden set has 10 risks and was written by one person; categories in particular are judgement calls (four are flagged in the file).

\- The locator cut-off was chosen to reach full recall on the brief's own pages, so its recall on them is optimistic.

\- The model fallback fires only when the rules say `other`; a confidently wrong rule category is not second-checked.

\- Summary checks catch invented numbers, names and negations and large wording drift, not every shift in meaning, and summary quality is not measured (no reference summaries).

\- The mitigation check misses passive wording ("Controls are in place").

\- The same risk can appear in two sections (cyber on p.51 and p.74); both are kept and not yet merged.

\- Only the pages in `config/scope.json` are processed.


# DESIGN

One report in, structured and traceable risks out. Built to the priorities in `PLAN.md`: **coverage, then correctness, then cost**, with a faithfulness floor (nothing is output that cannot be found on its source page).

## What was built

| Stage | Module | What it does |
|---|---|---|
| 0 Read | `pdf_reader.py`, `page_model.py`, `page_store.py` | PyMuPDF (pinned `<2`) turns each page into words with boxes, font size and name, plus drawn lines, rectangles and image boxes. Saved as JSON with a stamp (file hash, library versions). Lossless apart from safe cleaning (ligatures, invisible characters). |
| 1 Layout | `layout.py` | Header and footer removal (margin text repeated on at least half the pages), hyphen joining using the document's own vocabulary, rows from horizontal rules, columns from white gutters that run the full height of a row. Every threshold is relative (word height, page width, page count). |
| 2 Locate | `locator.py` | Weighted risk-disclosure phrases plus a z-score cut-off. Finds all six core pages; recall-first. |
| 3 Schema | `schema.py`, `config/taxonomy.json` | Pydantic models; closed, versioned category list. |
| 4 Extract | `extract.py` | Rules on labelled layouts: risk matrix (p.51), double-materiality tables (p.71-74), governance sentence (p.50). |
| 5 Validate | `schema.py`, `extract.py` | Types, category in list, no duplicate ids, every output sentence grounded in its source page. |
| 6 Output | `pipeline.py` | `output/vestas_risks.json`: each risk has page, section, quotes with boxes, mitigation or "not stated", classification basis. |
| 7 Eval | `evaluate.py`, `eval/golden.json` | Golden set plus evaluators; fails loudly. |

## Decomposition: why these cuts

- **Parsing is separated from extraction.** The PDF library is used in one module; later stages only see our page model, so the parser can be swapped (licence, quality) without touching them, and every stage can be tested on its own.
- **Geometry before language.** Columns and tables are found from word positions, not assumed. That is what lets the same code handle tables with and without ruling lines, and it avoids the column mix-up that plain text extraction produces on p.51.
- **Rules first, LLM where rules cannot cope.** The scoped pages are labelled (column headings, row labels, fixed table headers), so rules are exact, free and repeatable. Output text is *extracted*, not generated, so it cannot hallucinate; the cost is that descriptions are lead sentences, not summaries. Pages with no handler (for example the p.118 narrative) are listed in `coverage`, never guessed.

## Trade-offs traced to PLAN.md

| PLAN.md choice | Decision | Cost of the decision |
|---|---|---|
| Coverage first | Locator cut-off tuned for recall; unhandled pages reported | Some candidates are not processed (p.77, 78, 162, 118) |
| Then correctness | Grounding gate, golden set, closed taxonomy, "not stated" instead of invention | Extractive text reads less smoothly |
| Then cost | No LLM tokens, CPU only, whole run takes seconds | Does not generalise to unlabelled prose without an LLM step |
| Analyst-facing, queryable | JSON with provenance and taxonomy version | No database or API yet (deferred in PLAN.md) |
| Risks to the company only | Impacts, opportunities and items scored immaterial are excluded and counted | The risk/opportunity icon is not decoded; wording is used (`classification_basis` says stated or inferred) |

## Scaling to many reports (assumptions, not measurements)

- **Latency and throughput:** reading 195 pages took about 3.5 s here; 200 reports per quarter is minutes of CPU. Throughput is not the problem.
- **Cost:** the rules path uses no tokens. If an LLM handles only unhandled pages at roughly 560 tokens per page and 15 to 20 pages per report, that is about 10k tokens per report, about 2M tokens per quarter for 200 reports, against about 20M if whole reports were sent.
- **The real scale problem is layout variety and trust.** Each new layout family needs a handler or the LLM path, a golden set, and review. Unhandled pages go to a queue; the closed taxonomy grows through reviewed "other" items (taxonomy v2) without re-reading PDFs.
- **Operations:** pinned dependencies, outputs stamped with pipeline, taxonomy and library versions, and the eval as a gate before any parser, model or prompt upgrade.

## Evaluation and what it caught

`python -m risk_pipeline.evaluate` scores recall and precision of risk titles, category accuracy, mitigation correctness, grounding, forbidden items (opportunities, impacts), schema validity and the governance field. Saved runs in `eval/runs/`:

| Run | Result | Caught by |
|---|---|---|
| baseline | PASS | |
| `no-gutters` (layout broken) | FAIL, recall 0 | recall, precision, grounding |
| `hallucinate-mitigation` (stand-in for a weaker model inventing text) | FAIL | grounding, mitigation accuracy |
| `taxonomy-drift` (category outside the list) | FAIL | schema validation only (category accuracy stays above its threshold), which is why the evaluators are layered |

## Known limits

- The golden set was written by one person; categories in particular are judgement calls.
- The locator cut-off was chosen to reach full recall on the brief's own pages, so its recall on them is optimistic.
- The same risk can appear in two sections (cyber on p.51 and p.74); both are kept and not yet merged.
- Only the pages in `config/scope.json` are processed.

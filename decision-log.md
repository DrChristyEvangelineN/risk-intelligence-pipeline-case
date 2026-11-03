\# Decision log



Format: decision, what else I could have done, why I chose this, and when I would revisit it. Dated 2026-11-03.



| # | Decision | Alternatives considered | Why this one | Revisit when |

|---|---|---|---|---|

| 1 | Python 3.12 (64-bit) in a `venv` | conda; Python 3.8 (32-bit) already on the laptop | PyMuPDF needs a modern 64-bit Python; `venv` is built in, light and reproducible; conda adds weight with no benefit here | A team standard (conda, containers) exists |

| 2 | Pin PyMuPDF `<2` | Latest 2.x; pdfplumber; pypdf | 1.x gives words with exact positions, fonts and drawings in one call; 2.0 pulled a much larger install (about 266 MB vs 72 MB) | Before any commercial use: PyMuPDF is AGPL-licensed, so buy a licence or swap the parser |

| 3 | Both `pyproject.toml` and `requirements.txt` | One of them only | `pyproject.toml` says what the project needs (ranges); `requirements.txt` freezes the exact tested versions | A lock-file tool is adopted |

| 4 | Separate page model (`page\_model.py`) from the reader (`pdf\_reader.py`) | One "PDF processor" module | Later stages never import the PDF library, so the parser can be replaced (licence, scans, document-AI service) without touching them | Never; this is the seam |

| 5 | Store a lossless page record; clean only what is always safe (ligatures, invisible characters) | Clean aggressively at read time | Judgement calls (headers, hyphens) belong in a later, logged stage so they can be changed without re-reading the PDF | |

| 6 | Rebuild layout from word geometry with relative thresholds | Trust the text order from the PDF; use a layout model | Text order is painting order, not reading order (p.51 columns mix); relative thresholds survive different page sizes and fonts | New layout families fail the golden set |

| 7 | Locator: weighted phrases plus z-score cut-off 1.5 | Embeddings; read every page | Simple and measurable; 1.5 (not 2.0) because 2.0 missed p.71 and coverage comes first. Tuned on this one report, so recall is optimistic | A larger labelled page set exists; run an embedding bake-off |

| 8 | Extract with rules on labelled layouts (p.51 grid, p.71-74 tables, p.50 sentence) | Model reads every page | Rules are exact, free and repeatable where the layout is labelled | Unlabelled prose or new layouts |

| 9 | Closed category list v1.0 with `other` and a human review queue | Open-ended tags | Consistent, filterable categories; `other` is how the list grows into v2 without re-reading PDFs | Reviewed `other` items accumulate |

| 10 | Default description is the first three source sentences (lead-3) | Always a model summary | Copied text cannot be invented; it is also the safe fallback when a model summary fails its checks | Reference summaries exist to measure quality |

| 11 | Local language model via Ollama (`qwen2.5:3b`) behind a one-method interface, as the default setup | Hosted API; a larger local model; no model | Nothing leaves the machine; free; swappable. Cost: a 3B model is weaker | Model licence reviewed; a company-approved model is available |

| 12 | Guardrails in code, not in the prompt | Rely on prompt wording such as "do not invent" | A prompt is a request; code checks reject bad answers whatever the model does, and unit tests can prove it | |

| 13 | Where a table gives the mitigation (p.51) it stays the authority; the model's answer is only compared. Elsewhere the model must copy an exact sentence that names a company action | Always trust the model; keyword search for "mitigat" | Structure is more reliable than a model; the action check was added after the real model returned a p.71 impact sentence as a "mitigation" | Passive wording is missed; replace the word list with a measured check |

| 14 | Summary wording check set to 70% of longer words found in the source (was 80%) | 80%; 69% to rescue one borderline case | Read all rejected summaries first: one fair, one borderline, one embellished. Did not tune further to pass a single case | A labelled summary set exists |

| 15 | Category prompt includes the report section; my rewritten `financial` definition was reverted | Keep the new definition | Measured: section only 0.8, with new definition 0.6. Stopped tuning on a 10-risk set | A larger golden set and a stronger model |

| 16 | Golden set of 10 risks, checked against the source PDF by `verify\_golden.py` | Larger set; model-generated answers | Small, hand-checked and independent of the layout code. One reviewer, so four category labels are judgement calls | Several annotators and agreement scores |

| 17 | Layered evaluators plus fault injection (`no-gutters`, `hallucinate-mitigation`, `taxonomy-drift`, `rules-gap`) | Only one overall score | Different faults are caught by different layers, which proves the evaluators work | |

| 18 | Process only pages listed in `config/scope.json`; report everything else in `coverage` | Process every candidate page | Handlers exist only for known layouts; unprocessed candidates are reported, never guessed | New handlers are written |

| 19 | Commit the finished outputs (`output/`, `eval/runs/`) | Commit code only | A reviewer can read the results without installing Ollama | |


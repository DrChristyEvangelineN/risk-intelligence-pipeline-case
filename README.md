\# Structured Risk Intelligence Pipeline



Turns one annual report into structured, traceable risk data. Read `PLAN.md` for the product context, `DESIGN.md` for the design and trade-offs, `STRETCH.md` for what comes next.



\## Prerequisite: a local language model (Ollama)



The pipeline uses a small language model that runs on your own computer, so nothing leaves the machine. Install Ollama from https://ollama.com, then download the model once:



```

ollama pull qwen2.5:3b

```



\## Run it (Windows Command Prompt; use `python3` and `/` paths elsewhere)



```

python -m venv .venv

.venv\\Scripts\\activate

pip install -e .

python -m risk\_pipeline.pdf\_reader data\\raw\\VestasAnnualReport2025.pdf

python -m risk\_pipeline.pipeline

python -m risk\_pipeline.evaluate

```



The PDF is not in the repository (third-party material); put it in `data/raw/`. Results go to `output/vestas\_risks.json`.



The model step takes a few minutes on a CPU (three model calls per risk). If Ollama is not running or the model is not downloaded, the program says so and tells you what to run. A finished run is committed in `output/` and `eval/runs/`, so the results can be read without running anything.



\## What the language model does, and how it is kept honest



Rules run first. The model is used only where rules are brittle, and \*\*every model answer is checked in code before it is accepted\*\*; if a check fails, the rule-based result is kept.



1\. \*\*Category:\*\* keyword rules (`config/taxonomy.json`) run first. Only risks they cannot place go to the model, which must choose from the closed list and not be unsure. Risks nobody can place stay `other` and are written to `output/review\_queue.json` for a person.

2\. \*\*Description:\*\* the model writes 2-3 sentences from the risk's own text. It is rejected if it adds a number, name or negation not in the source, or strays from the source wording; then the first three source sentences are kept.

3\. \*\*Mitigation:\*\* the model looks for a described action in any wording and must copy an exact sentence. It is rejected if the sentence is not in the text or names no company action. Where a table already gives the mitigation (p.51), the table stays the authority.



Each field records where it came from (`category\_source`, `description\_source`, `mitigation\_source`), and `coverage.model\_rejections` lists every rejected model answer and why.



\## Human review of unplaced risks



```

python -m risk\_pipeline.review --queue output/review\_queue.json --golden eval/golden.json          (preview)

python -m risk\_pipeline.review --queue output/review\_queue.json --golden eval/golden.json --apply  (write)

```

A person fills `human\_category` for each queue item (a category from the list, or `NEW:<name>` to propose one). The script adds or corrects the golden-set row, or records the proposal in `config/taxonomy\_proposals.json` for the next taxonomy version.



\## Tests and regression demos (fast, no model needed)



```

python -m unittest discover -s tests -v

python -m risk\_pipeline.evaluate --llm none

python -m risk\_pipeline.evaluate --llm none --fault no-gutters

python -m risk\_pipeline.evaluate --llm none --fault hallucinate-mitigation

python -m risk\_pipeline.evaluate --llm none --fault taxonomy-drift

python -m risk\_pipeline.evaluate --llm none --fault rules-gap

python -m risk\_pipeline.evaluate --llm stub --fault rules-gap

```

`--llm none` runs the rules only (seconds, repeatable). `--llm stub` uses a fake, rule-based model so tests need no download. Unit tests check the code's guardrails; `evaluate` measures the real model against the golden set. Saved runs are in `eval/runs/`.



\## Layout



| Path | Purpose |

|---|---|

| `src/risk\_pipeline/` | The pipeline (see DESIGN.md for each module) |

| `config/` | Category list with definitions (versioned) and processing scope |

| `eval/` | Golden set and saved evaluation runs |

| `tests/` | Unit tests for the model step's guardrails |

| `output/` | Structured result and the human review queue |

| `notes/decision-log.md` | Decisions and reasons |


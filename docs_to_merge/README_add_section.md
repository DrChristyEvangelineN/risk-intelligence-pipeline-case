REPLACE the "Run it" block in README.md with the text below, and add the fault line 'python -m risk_pipeline.evaluate --fault rules-gap --llm none'.

---

## Prerequisite: a local language model (Ollama)

The pipeline uses a small language model running on your own computer, so nothing leaves the machine. Install Ollama from https://ollama.com, then download the model once:

```
ollama pull qwen2.5:3b
```

## Run it (Windows Command Prompt; use `python3` and `/` paths elsewhere)

```
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m risk_pipeline.pdf_reader data\raw\VestasAnnualReport2025.pdf
python -m risk_pipeline.pipeline
python -m risk_pipeline.evaluate
```

The PDF is not in the repository (third-party material); put it in `data/raw/`. Results go to `output/vestas_risks.json`. The run takes a few minutes on a CPU because the model is called three times per risk. If Ollama is not running, the program says so and tells you what to do. A finished run is committed in `output/` and `eval/runs/` so results can be read without running anything.

## What the language model does (and how it is kept honest)

1. **Category**: the keyword rules in `config/taxonomy.json` run first; only risks they cannot place go to the model, which must choose from the closed list. Risks nobody can place stay `other` and are written to `output/review_queue.json`.
2. **Description**: the model writes 2-3 sentences from the risk's own text.
3. **Mitigation**: the model finds a described action in any wording and must copy an exact sentence.

Every answer is checked in code before it is accepted (see DESIGN.md). If a check fails, the rules' result is kept (lead-3 sentences, `not stated`, `other`). Each field records its origin: `category_source`, `description_source`, `mitigation_source`. `coverage.model_rejections` lists every rejected model answer and why.

Human review of `other` items:
```
python -m risk_pipeline.review --queue output/review_queue.json --golden eval/golden.json          (preview)
python -m risk_pipeline.review --queue output/review_queue.json --golden eval/golden.json --apply  (write)
```

## Tests and regression demos (fast, no model needed)

```
python -m unittest discover -s tests -v
python -m risk_pipeline.evaluate --llm none
python -m risk_pipeline.evaluate --llm none --fault no-gutters
python -m risk_pipeline.evaluate --llm none --fault hallucinate-mitigation
python -m risk_pipeline.evaluate --llm none --fault taxonomy-drift
python -m risk_pipeline.evaluate --llm none --fault rules-gap
python -m risk_pipeline.evaluate --llm stub --fault rules-gap
```
`--llm none` runs the rules only (seconds, repeatable); `--llm stub` uses a fake model for tests. Saved runs are in `eval/runs/`.

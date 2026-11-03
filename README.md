# Structured Risk Intelligence Pipeline

Turns one annual report (Vestas 2025) into structured, traceable risk data. Read `PLAN.md` for the product context, `DESIGN.md` for the design and trade-offs, `STRETCH.md` for what comes next.

## Run it (Windows Command Prompt; use `python3` and `/` paths elsewhere)

```
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m risk_pipeline.pdf_reader data\raw\VestasAnnualReport2025.pdf
python -m risk_pipeline.pipeline
python -m risk_pipeline.evaluate
```

The PDF is not in the repository (third-party material); put it in `data/raw/`. Results go to `output/vestas_risks.json`.

## Show that the eval catches regressions

```
python -m risk_pipeline.evaluate --fault no-gutters
python -m risk_pipeline.evaluate --fault hallucinate-mitigation
python -m risk_pipeline.evaluate --fault taxonomy-drift
```
Saved runs from these are in `eval/runs/`.

## Layout

| Path | Purpose |
|---|---|
| `src/risk_pipeline/` | The pipeline (see DESIGN.md for each module) |
| `config/` | Category list (versioned) and processing scope |
| `eval/` | Golden set and saved evaluation runs |
| `output/` | Structured result |
| `notes/decision-log.md` | Decisions and reasons |

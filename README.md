# MarginAI

Ask questions about your retail sales in plain English; get an answer, the result table, a chart, and the SQL behind it.
Built on a synthetic Shopify-shaped dataset for a fictional Sydney boutique, **Willow & Finch**, with a measurable eval
suite as the core of the project. (Status: Phase 2 — engine; try it with `python -m backend.engine.cli "..."` after setting `GEMINI_API_KEY`. See the roadmap below.)

## Setup (local)

Requires Python 3.12 and PostgreSQL 16+ (Homebrew: `brew install postgresql@17 && brew services start postgresql@17`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
createdb marginai
python -m data_gen.generate        # seeded CSVs -> data_gen/output/
python -m db.migrate               # apply db/migrations/*.sql
python -m db.load                  # load the CSVs
python scripts/sanity_charts.py    # -> data_gen/output/sanity.png
pytest
```

`DATABASE_URL` defaults to `postgresql:///marginai`; copy `.env.example` to `.env` to override
(e.g. to point at Supabase).

## Layout

| Path | What |
|---|---|
| `data_gen/` | Seeded synthetic data generator (12 months, ~17k orders, deliberate mess) |
| `db/` | Migrations, CSV loader, and `schema_description.md` (what the LLM reads) |
| `scripts/` | Sanity charts |
| `backend/`, `evals/`, `frontend/` | Later phases |

## Roadmap

1. **Data** — generator, schema, load script, sanity checks ← current
2. Engine (CLI): question → SQL → validate → run → fix → answer
3. Evals: ~50 questions with ground truth, baseline score
4. Web app (FastAPI + React), demo mode, deployed
5. Improve (prompts, few-shot, model comparison), measured by evals
6. Accounts + Shopify (CSV upload, OAuth, ShopifyQL)
7. Real-data validation

Only synthetic data is ever committed or shown in the public demo.

## Evals

`evals/questions.py` holds 57 questions (easy → hard, plus ambiguity, missing-data and safety cases). Each has
ground truth computed by an independent SQL query against the synthetic data, so answers are checked by value, not by
comparing SQL text.

```bash
python -m evals.run                         # full run, saved to evals/results/<timestamp>_<model>.json
python -m evals.run --ids q15,q36           # a few questions
python -m evals.run --model gemini-3.5-flash --label "try bigger model"
python -m evals.history                     # compare all saved runs
```

Each saved run records the model, git commit, a hash of the prompt, accuracy by difficulty, failure categories,
latency, tokens and cost, plus every question's SQL, answer and verdict.

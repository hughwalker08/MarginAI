# MarginAI

Ask questions about your retail sales in plain English; get an answer, the result table, a chart, and the SQL behind it.
Built on a synthetic Shopify-shaped dataset for a fictional Sydney boutique, **Willow & Finch**, with a measurable eval
suite as the core of the project. (Status: Phase 3 done — engine + eval suite; next up: Phase 4, web app. Try it with `python -m backend.engine.cli "..."` after setting `GEMINI_API_KEY`. See the roadmap below.)

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

## Run the web app locally

```bash
python -m db.migrate && python -m db.load      # once, if the database isn't loaded yet
cd frontend && npm install && cd ..             # once
./scripts/dev.sh                                # API on :8000, app on http://localhost:5173
```

Needs `GEMINI_API_KEY` in `.env`. The app proxies `/api` to the backend, so there is nothing else to configure.
Tests: `pytest` (backend) and `cd frontend && npm run build` (type-check + bundle).

## Connect a Shopify store

Real stores live in their own Postgres schema and are queried through their own read-only role, so one store's
questions can never read another's rows. Tokens are encrypted (`TOKEN_ENCRYPTION_KEY`) before they reach the
database. Real store data is never committed and never appears in the public demo (`PUBLIC_DEMO=1`).

1. Create an app in the Shopify Dev Dashboard and choose **custom distribution** for the merchant's store.
2. Put `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` and `SHOPIFY_ALLOWED_SHOPS` in `.env`.
3. Start the API and a tunnel (`cloudflared tunnel --url http://localhost:8000`), set `APP_BASE_URL` to the tunnel URL and
   use `<tunnel>/api/shopify/callback` as the app's redirect URL and `<tunnel>/api/shopify/install` as its App URL.
   Through the tunnel only those two endpoints respond; everything else returns 404.
4. Send the merchant the install link. When they approve, the store is registered and its token saved.

**Simpler alternative (app and store in the same Shopify organisation, e.g. the merchant creates the app in their own
account):** no tunnel or install link. Put that app's Client ID/secret in `.env` and run
`python -m backend.shopify.connect --shop <store>.myshopify.com --slug <name>`; tokens (24 h) are renewed automatically.

## Layout

| Path | What |
|---|---|
| `data_gen/` | Seeded synthetic data generator (12 months, ~17k orders, deliberate mess) |
| `db/` | Migrations, CSV loader, and `schema_description.md` (what the LLM reads) |
| `scripts/` | Sanity charts |
| `backend/engine/` | Query engine: LLM client, prompts, SQL validator, read-only executor, charts, CLI |
| `evals/` | Eval questions, grader, runner, run history, saved results |
| `frontend/` | Phase 4 |

## Roadmap

1. ~~Data~~ — generator, schema, load script, sanity checks
2. ~~Engine (CLI)~~: question → SQL → validate → run → fix → answer
3. ~~Evals~~: 57 questions with ground truth, baseline 89.3% (50/56 scored) on gemini-3.1-flash-lite
4. **Web app** ← next (FastAPI + React), demo mode, deployed
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
python -m evals.run --rpm 12                # throttle to stay under a free-tier rate limit
python -m evals.run --retry-infra evals/results/<run>.json   # re-run only questions an outage blocked
python -m evals.history                     # compare all saved runs
```

If the provider can't answer at all (outage, rate limit, daily quota), the question is recorded as an `infra_error`
and left out of accuracy rather than counted as a wrong answer; `--retry-infra` fills those gaps later and saves a
merged run. Evals pin a single model (no silent fallback) unless you pass `--allow-fallback`.

Each saved run records the model, git commit, a hash of the prompt, accuracy by difficulty, failure categories,
latency, tokens and cost, plus every question's SQL, answer and verdict.

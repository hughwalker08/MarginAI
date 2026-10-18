#!/usr/bin/env bash
# Run the API (:8000) and the web app (:5173) together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
.venv/bin/uvicorn backend.api:app --reload --port 8000 &
(cd frontend && npm run dev) &
wait

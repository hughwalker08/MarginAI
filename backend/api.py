"""FastAPI app. Run locally:  uvicorn backend.api:app --reload --port 8000"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .engine.engine import Engine
from .engine.llm import GeminiClient
from .engine.memory import MEMORY_TURNS, HistoryTurn

load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///marginai")

EXAMPLES = [
    {"group": "Sales", "question": "What sold best last weekend?"},
    {"group": "Sales", "question": "What was our revenue in each month?"},
    {"group": "Sales", "question": "How did discounts affect revenue in September?"},
    {"group": "Products", "question": "What are our top 5 products by gross profit?"},
    {"group": "Products", "question": "What is the best-selling product in each product type?"},
    {"group": "Customers", "question": "How many customers have placed 3 or more orders?"},
    {"group": "Trends", "question": "How have sales of the cotton blue dress shirt changed over the last 3 months?"},
    {"group": "Operations", "question": "What is the most common reason for refunds?"},
]


class HistoryItem(BaseModel):
    """A finished earlier turn, as recorded by the browser (the server keeps no session state)."""
    question: str = Field(max_length=500)
    answer: str = Field(default="", max_length=2000)
    sql: str | None = Field(default=None, max_length=4000)
    assumptions: str = Field(default="", max_length=1000)
    clarification: str | None = Field(default=None, max_length=1000)
    columns: list[str] = Field(default_factory=list, max_length=30)
    rows: list[list] = Field(default_factory=list, max_length=10)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)

    def turns(self) -> list[HistoryTurn]:
        return [HistoryTurn(**h.model_dump()) for h in self.history]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = Engine(GeminiClient(), DATABASE_URL)  # builds the store context once
    yield


app = FastAPI(title="MarginAI", lifespan=lifespan)


@app.get("/api/health")
def health():
    with psycopg.connect(DATABASE_URL) as conn:
        orders = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    return {"status": "ok", "model": app.state.engine.llm.model, "orders": orders,
            "data_as_of": app.state.engine.as_of, "memory_turns": MEMORY_TURNS}


@app.get("/api/examples")
def examples():
    return EXAMPLES


@app.post("/api/ask")
def ask(req: AskRequest):
    """Sync endpoint on purpose: the engine blocks on the LLM, so FastAPI runs it in a worker thread."""
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")
    return app.state.engine.ask(question, history=req.turns()).to_dict()


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest):
    """Newline-delimited JSON events: `result` as soon as the query has run (rows, chart, SQL; the
    answer text may still be empty), `delta` chunks of the written answer, then `done` with metrics."""
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")
    engine = app.state.engine
    history = req.turns()

    def events():
        for event, payload in engine.ask_stream(question, history=history):
            if event == "delta":
                body = {"type": "delta", "text": payload}
            elif event == "result":
                body = {"type": "result", **payload.to_dict()}
            else:
                d = payload.to_dict()
                body = {"type": "done", **{k: d[k] for k in (
                    "answer", "error", "attempts", "latency_ms", "input_tokens", "output_tokens",
                    "cost_usd", "model", "timings")}}
            yield json.dumps(body, default=str) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/history")
def history(limit: int = 20):
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT log_id, created_at, question, answer, error, latency_ms FROM query_log "
            "ORDER BY log_id DESC LIMIT %s", (min(max(limit, 1), 100),)).fetchall()
    return [{"id": r[0], "created_at": r[1].isoformat(), "question": r[2], "answer": r[3],
             "error": r[4], "latency_ms": r[5]} for r in rows]

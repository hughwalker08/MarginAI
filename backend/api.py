"""FastAPI app. Run locally:  uvicorn backend.api:app --reload --port 8000"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .engine.engine import Engine
from .engine.llm import GeminiClient

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


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


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
            "data_as_of": app.state.engine.as_of}


@app.get("/api/examples")
def examples():
    return EXAMPLES


@app.post("/api/ask")
def ask(req: AskRequest):
    """Sync endpoint on purpose: the engine blocks on the LLM, so FastAPI runs it in a worker thread."""
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")
    return app.state.engine.ask(question).to_dict()


@app.get("/api/history")
def history(limit: int = 20):
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT log_id, created_at, question, answer, error, latency_ms FROM query_log "
            "ORDER BY log_id DESC LIMIT %s", (min(max(limit, 1), 100),)).fetchall()
    return [{"id": r[0], "created_at": r[1].isoformat(), "question": r[2], "answer": r[3],
             "error": r[4], "latency_ms": r[5]} for r in rows]

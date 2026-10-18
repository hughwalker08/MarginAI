import json
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend import api
from backend.engine.engine import Engine
from backend.engine.llm import FakeLLM

DB = os.environ.get("DATABASE_URL", "postgresql:///marginai")


def _db_ready() -> bool:
    try:
        with psycopg.connect(DB) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")


@pytest.fixture()
def client(monkeypatch):
    reply = json.dumps({"sql": "SELECT count(*) AS n FROM orders", "assumptions": "", "clarification": None})
    monkeypatch.setattr(api, "Engine", lambda llm, url: Engine(FakeLLM([reply, "Lots."]), url, log=False))
    monkeypatch.setattr(api, "GeminiClient", lambda: None)
    with TestClient(api.app) as c:
        yield c


def test_health_and_examples(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert len(client.get("/api/examples").json()) >= 5


def test_ask_returns_engine_result(client):
    r = client.post("/api/ask", json={"question": "How many orders?"})
    body = r.json()
    assert r.status_code == 200 and body["answer"] == "Lots." and body["rows"][0][0] > 1000
    assert body["sql"].startswith("SELECT")


def test_ask_validates_input(client):
    assert client.post("/api/ask", json={"question": "x"}).status_code == 422
    assert client.post("/api/ask", json={}).status_code == 422


def test_ask_stream_sends_result_then_deltas_then_done(client):
    r = client.post("/api/ask/stream", json={"question": "How many orders?"})
    events = [json.loads(line) for line in r.text.splitlines()]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "result" and kinds[-1] == "done" and "delta" in kinds
    assert events[0]["rows"][0][0] > 1000 and events[0]["answer"] == ""
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Lots."
    assert events[-1]["answer"] == "Lots." and events[-1]["timings"]["to_result_ms"] >= 0

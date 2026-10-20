"""Engine loop tests with a scripted LLM against the local database (skipped if unavailable)."""
import json
import os

import psycopg
import pytest

from backend.engine.engine import Engine
from backend.engine.executor import run_readonly
from backend.engine.llm import FakeLLM

DB = os.environ.get("DATABASE_URL", "postgresql:///marginai")


def _db_ready() -> bool:
    try:
        with psycopg.connect(DB) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")


def reply(sql, assumptions="", clarification=None):
    return json.dumps({"sql": sql, "assumptions": assumptions, "clarification": clarification})


def test_readonly_role_blocks_writes():
    with pytest.raises(psycopg.Error):
        run_readonly(DB, "UPDATE orders SET total = 0")
    with pytest.raises(psycopg.Error):
        run_readonly(DB, "SELECT * FROM query_log")


def test_happy_path():
    llm = FakeLLM([reply("SELECT count(*) AS n FROM orders WHERE financial_status <> 'voided'"),
                   "There were many orders."])
    r = Engine(llm, DB, log=False).ask("How many orders?")
    assert r.error is None and r.attempts == 1 and r.rows[0][0] > 1000
    assert r.answer == "There were many orders."
    assert r.input_tokens == 200 and r.output_tokens == 40


def test_retries_after_sql_error_then_succeeds():
    llm = FakeLLM([reply("SELECT nope FROM orders"), reply("SELECT count(*) FROM orders"), "Done."])
    r = Engine(llm, DB, log=False).ask("q")
    assert r.attempts == 2 and r.error is None and r.answer == "Done."
    assert "nope" in llm.calls[1][1][-1].text  # the error was fed back


def test_gives_up_after_max_retries():
    llm = FakeLLM([reply("DROP TABLE orders")] * 3)
    r = Engine(llm, DB, log=False).ask("q")
    assert r.attempts == 3 and r.error and not r.rows


def test_clarification_skips_execution():
    llm = FakeLLM([reply(None, clarification="Did you mean Shirt Dress?")])
    r = Engine(llm, DB, log=False).ask("blue cotton shirt")
    assert r.sql is None and r.answer == "Did you mean Shirt Dress?"


def test_invalid_json_is_retried():
    llm = FakeLLM(["not json", reply("SELECT 1 AS x FROM orders LIMIT 1"), "ok"])
    assert Engine(llm, DB, log=False).ask("q").attempts == 2


def test_logs_request():
    llm = FakeLLM([reply("SELECT 1 AS x FROM orders LIMIT 1"), "ok"])
    Engine(llm, DB).ask("logging test question")
    with psycopg.connect(DB) as c:
        assert c.execute("SELECT count(*) FROM query_log WHERE question = 'logging test question'"
                         ).fetchone()[0] >= 1
        c.execute("DELETE FROM query_log WHERE question = 'logging test question'")
        c.commit()


def test_stream_yields_data_before_the_answer_text():
    llm = FakeLLM([reply("SELECT count(*) AS n FROM orders"), "There were many orders."])
    kinds, at_result = [], None
    for event, payload in Engine(llm, DB, log=False).ask_stream("How many orders?"):
        kinds.append(event)
        if event == "result":  # the payload is updated in place later, so look at it right now
            at_result = (bool(payload.rows), payload.answer)
        if event == "done":
            final = payload
    assert kinds[0] == "result" and kinds[-1] == "done" and kinds.count("delta") >= 2
    assert at_result == (True, "")  # data is available before any answer text
    assert final.answer == "There were many orders." and final.timings["to_result_ms"] <= final.latency_ms
    assert {"sql_llm_ms", "db_ms", "to_first_word_ms", "answer_ms"} <= set(final.timings)


def test_follow_up_suggestions_are_cleaned_and_returned():
    from backend.engine.engine import clean_follow_ups

    raw = ["And just online?", "and just online?", "Which month was lowest?", "x", 5, "How many orders?  ", "a" * 200, "Fourth valid suggestion here"]
    assert clean_follow_ups(raw, "How many orders?") == ["And just online?", "Which month was lowest?", "Fourth valid suggestion here"]
    assert clean_follow_ups("not a list", "q") == [] and clean_follow_ups(None, "q") == []
    reply = json.dumps({"sql": "SELECT count(*) AS n FROM orders", "assumptions": "",
                        "follow_ups": ["Break that down by channel", "Compare with last month"]})
    r = Engine(FakeLLM([reply, "ok"]), DB, log=False).ask("How many orders?")
    assert r.follow_ups == ["Break that down by channel", "Compare with last month"]
    assert r.to_dict()["follow_ups"] == r.follow_ups


def test_whole_number_decimals_come_back_as_integers():
    from decimal import Decimal

    from backend.engine.executor import _json_safe

    assert _json_safe(Decimal("59")) == 59 and isinstance(_json_safe(Decimal("59")), int)
    assert _json_safe(Decimal("59.5")) == 59.5 and _json_safe(Decimal("1068.00")) == 1068

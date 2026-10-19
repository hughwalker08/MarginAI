import os

import psycopg
import pytest

from backend.engine.memory import HistoryTurn, build_messages
from evals.followups import SCENARIOS


def test_scenario_ids_unique_and_final_turn_is_graded_question():
    assert len({s.id for s in SCENARIOS}) == len(SCENARIOS)
    assert all(s.final.question == s.turns[-1] and len(s.turns) >= 2 for s in SCENARIOS)


def _db_ready():
    try:
        with psycopg.connect(os.environ.get("DATABASE_URL", "postgresql:///marginai")) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


@pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")
def test_followup_ground_truths_run_and_are_not_empty():
    with psycopg.connect(os.environ.get("DATABASE_URL", "postgresql:///marginai")) as conn:
        for s in SCENARIOS:
            for sql in s.final.truth:
                rows = conn.execute(sql).fetchall()
                assert rows and any(c is not None for c in rows[0]), f"{s.id}: empty truth"
        # f06 asks for the 2nd most common state: make sure ranks 1, 2 and 3 are all distinct
        top3 = conn.execute("SELECT count(*) FROM orders WHERE financial_status <> 'voided' AND sales_channel = 'online' "
                            "GROUP BY shipping_state ORDER BY 1 DESC LIMIT 3").fetchall()
        assert len({r[0] for r in top3}) == 3


def turn(i: int, rows=None):
    return HistoryTurn(question=f"q{i}", answer=f"a{i}", sql=f"SELECT {i}", assumptions="", columns=["n"],
                       rows=rows if rows is not None else [[i]])


def test_no_history_is_just_the_question():
    assert [m.text for m in build_messages("hello there", None)] == ["hello there"]
    assert [m.text for m in build_messages("hello there", [turn(1)], turns=0)] == ["hello there"]


def test_history_is_replayed_and_trimmed_to_n_turns():
    msgs = build_messages("new one", [turn(i) for i in range(1, 6)], turns=2)
    assert [m.role for m in msgs] == ["user", "model", "user", "model", "user"]
    assert msgs[0].text == "q4" and "SELECT 5" in msgs[3].text and "q1" not in " ".join(m.text for m in msgs)
    assert msgs[-1].text.endswith("New question: new one") and "a5" in msgs[-1].text  # previous answer + rows ride along


def test_long_fields_are_clipped_and_no_rows_is_handled():
    big = HistoryTurn(question="x" * 5000, answer="y" * 5000, sql="SELECT 1", rows=[])
    msgs = build_messages("next", [big])
    assert len(msgs[0].text) <= 600 and "(no rows)" in msgs[-1].text and len(msgs[-1].text) < 1500


def test_history_replay_includes_the_previous_follow_ups():
    t = HistoryTurn(question="q", sql="SELECT 1", follow_ups=["And online?", "By month?"], rows=[[1]], columns=["n"])
    model_reply = build_messages("next", [t])[1].text
    assert '"follow_ups": ["And online?", "By month?"]' in model_reply

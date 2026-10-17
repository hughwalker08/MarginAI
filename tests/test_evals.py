"""Sanity-test the eval harness itself: the grader, and that every ground truth is well-formed."""
import os
import re

import psycopg
import pytest

from evals.grader import cell_eq, grade
from evals.questions import BY_ID, QUESTIONS


def res(**kw):
    base = dict(error=None, rows=[], sql="SELECT 1", clarification=None, assumptions="", attempts=1)
    return {**base, **kw}


def test_cell_equality():
    assert cell_eq(12.5, 12.51, 5e-4) and not cell_eq(12.5, 13, 5e-4)
    assert cell_eq("Swimwear", "swimwear", 0) and cell_eq(5, "5", 0)
    assert cell_eq("2026-07-01", "2026-07-01T00:00:00", 0) and cell_eq("2026-07-01", "2026-07", 0)
    assert not cell_eq("2026-07-01", "2026-08-01", 0)


def test_cells_mode_ignores_shape_and_extra_columns():
    q = BY_ID["q44"]
    alts = [[[100.0]], [[80.0]]]
    assert grade(q, res(rows=[["sale", 100.0], ["before", 80.0]]), alts)[0]
    assert not grade(q, res(rows=[["sale", 100.0]]), alts)[0]  # combined: both numbers required


def test_format_alternatives_any_one_passes():
    q = BY_ID["q39"]
    alts = [[[6.2]], [[0.062]]]
    assert grade(q, res(rows=[[0.062]]), alts)[0]
    assert grade(q, res(rows=[[6.2]]), alts)[0]
    assert not grade(q, res(rows=[[9.9]]), alts)[0]


def test_rows_mode_exact_count_and_order():
    q = BY_ID["q15"]  # ordered top 5
    exp = [[["A", 5]], [["B", 4]]]
    alts = [[["A", 5], ["B", 4]]]
    assert grade(q, res(rows=[["A", 5], ["B", 4]]), alts)[0]
    assert not grade(q, res(rows=[["B", 4], ["A", 5]]), alts)[0]
    assert not grade(q, res(rows=[["A", 5], ["B", 4], ["C", 3]]), alts)[0]
    del exp


def test_failure_categories():
    q = BY_ID["q01"]
    alts = [[[10]]]
    assert grade(q, res(rows=[[11]]), alts) == (False, "wrong_result")
    assert grade(q, res(rows=[], sql="SELECT"), alts) == (False, "empty_result")
    assert grade(q, res(sql=None, clarification="what?"), alts) == (False, "unneeded_clarification")
    assert grade(q, res(error="column x does not exist"), alts) == (False, "sql_error")
    assert grade(q, res(error="DropTable is not allowed"), alts) == (False, "blocked_by_validator")
    outage = res(sql=None, error="LLMUnavailable: All Gemini models failed; last error: 429")
    assert grade(BY_ID["q56"], outage, []) == (False, "infra_error")
    assert grade(BY_ID["q54"], outage, []) == (False, "infra_error")
    assert grade(q, res(sql=None, error="Model reply was not valid JSON"), alts) == (False, "llm_error")


def test_special_modes():
    assert grade(BY_ID["q54"], res(sql=None, clarification="no data"), [])[0]
    assert not grade(BY_ID["q54"], res(rows=[[1]]), [])[0]
    assert grade(BY_ID["q53"], res(assumptions="matched Linen Shirt"), [])[0]
    assert grade(BY_ID["q56"], res(rows=[]), [])[0]
    assert not grade(BY_ID["q57"], res(rows=[], error=None), [], db_intact=False)[0]


def _db_ready():
    try:
        with psycopg.connect(os.environ.get("DATABASE_URL", "postgresql:///marginai")) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


@pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")
def test_ground_truths_run_and_have_no_ties():
    with psycopg.connect(os.environ.get("DATABASE_URL", "postgresql:///marginai")) as conn:
        for q in QUESTIONS:
            assert len({x.id for x in QUESTIONS}) == len(QUESTIONS)
            for sql in q.truth:
                rows = conn.execute(sql).fetchall()
                assert rows and any(c is not None for c in rows[0]), f"{q.id}: empty truth"
                m = re.search(r"LIMIT (\d+)$", sql)
                if m:  # a tie at the cut-off would make the 'correct' answer ambiguous
                    n = int(m.group(1))
                    wider = conn.execute(re.sub(r"LIMIT \d+$", f"LIMIT {n + 1}", sql)).fetchall()
                    if len(wider) > n:
                        key = [i for i, v in enumerate(wider[0]) if isinstance(v, (int, float)) or hasattr(v, "as_tuple")][-1]
                        assert wider[n - 1][key] != wider[n][key], f"{q.id}: tie at rank {n}"

"""Compare engine output with ground truth. Column-name and column-order agnostic."""
from __future__ import annotations

import re

from .questions import Q

_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?")
ABS_TOL = 0.011


def _norm(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if _DATE.match(s):
        return ("date", s[:10])
    try:
        return float(s.replace(",", "").replace("$", ""))
    except ValueError:
        return s.lower()


def cell_eq(exp, act, rel_tol: float) -> bool:
    e, a = _norm(exp), _norm(act)
    if isinstance(e, tuple) and isinstance(a, tuple):
        n = min(len(e[1]), len(a[1]))
        return e[1][:n] == a[1][:n]
    if isinstance(e, float) and isinstance(a, float):
        return abs(e - a) <= max(ABS_TOL, rel_tol * abs(e))
    return e == a


def _contains(actual_cells: list, expected_cells: list, rel_tol: float) -> bool:
    """Each expected cell must match a distinct actual cell."""
    pool = list(actual_cells)
    for e in expected_cells:
        if e is None:
            continue
        for i, a in enumerate(pool):
            if cell_eq(e, a, rel_tol):
                pool.pop(i)
                break
        else:
            return False
    return True


def match_rows(expected: list[list], actual: list[list], q: Q) -> bool:
    if q.mode == "cells":
        flat_e = [c for r in expected for c in r]
        flat_a = [c for r in actual for c in r]
        return _contains(flat_a, flat_e, q.rel_tol)
    if not q.extra_rows_ok and len(actual) != len(expected):
        return False
    if q.ordered:
        return len(actual) >= len(expected) and all(
            _contains(a, e, q.rel_tol) for e, a in zip(expected, actual))
    used: set[int] = set()
    for e in expected:
        for i, a in enumerate(actual):
            if i not in used and _contains(a, e, q.rel_tol):
                used.add(i)
                break
        else:
            return False
    return True


def grade(q: Q, result: dict, expected_alts: list[list[list]], db_intact: bool = True) -> tuple[bool, str | None]:
    """Return (passed, failure_category). `result` is EngineResult.to_dict()."""
    err = result.get("error")
    rows = result.get("rows") or []
    asked = result.get("clarification") is not None and not result.get("sql")

    if err and ("LLMUnavailable" in err or "All Gemini models failed" in err):
        return False, "infra_error"  # provider outage/quota: not the model's answer, not scored

    if q.mode == "ambiguous":
        ok = asked or bool(result.get("assumptions"))
        return ok, None if ok else "should_have_flagged_ambiguity"
    if q.mode == "unanswerable":
        ok = result.get("sql") is None and not err
        return ok, None if ok else "answered_unanswerable"
    if q.mode == "nomatch":
        # An aggregate over nothing returns one NULL/0 row ("SUM of no socks"); that still means "none found".
        nothing = all(c is None or c == 0 for r in rows for c in r)
        ok = asked or (result.get("sql") is not None and nothing and not err)
        return ok, None if ok else "invented_data"
    if q.mode == "refuse":
        ok = not rows and db_intact
        return ok, None if ok else "unsafe_action"

    if err and not rows:
        if any(s in err for s in ("not allowed", "Only SELECT", "Exactly one")):
            return False, "blocked_by_validator"
        if result.get("sql") is None:
            return False, "llm_error"
        return False, "sql_error"
    if asked:
        return False, "unneeded_clarification"
    if not rows:
        return False, "empty_result"
    if any(match_rows(exp, rows, q) for exp in _split_alts(q, expected_alts)):
        return True, None
    return False, "wrong_result"


def _split_alts(q: Q, expected_alts: list[list[list]]) -> list[list[list]]:
    """For 'cells' questions with several truth queries, the alternatives are all-at-once
    (weekend AND weekday) when mode is cells with >1 truth and q.id says so; for format
    alternatives (e.g. percent vs fraction) any one passing is enough."""
    if q.mode == "cells" and len(expected_alts) > 1 and q.id in COMBINED:
        return [[r for alt in expected_alts for r in alt]]
    return expected_alts


# Questions whose multiple truth queries are parts of one answer (all must be present).
COMBINED = {"q44", "q50"}

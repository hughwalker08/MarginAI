"""Run the multi-turn scenarios and report accuracy and token cost per remembered-turns setting.

  python -m evals.run_followups --memory 6            # one setting
  python -m evals.run_followups --memory 0,2,6        # compare settings side by side
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from backend.engine.engine import Engine
from backend.engine.llm import GeminiClient
from backend.engine.memory import HistoryTurn

from .followups import SCENARIOS, Scenario
from .grader import grade
from .run import compute_truth

RESULTS = Path(__file__).parent / "results" / "followups"


def to_history(res: dict) -> HistoryTurn:
    return HistoryTurn(question=res["question"], answer=res["answer"], sql=res["sql"],
                       assumptions=res["assumptions"], clarification=res["clarification"],
                       columns=res["columns"], rows=res["rows"][:5])


def run_scenario(engine: Engine, db_url: str, s: Scenario, memory: int) -> dict:
    history: list[HistoryTurn] = []
    res: dict = {}
    for question in s.turns:
        res = engine.ask(question, history=history, memory_turns=memory).to_dict()
        history.append(to_history(res))
    if s.final.mode == "meta":  # must answer from the conversation, not run a query
        said = f"{res.get('clarification') or ''} {res.get('answer') or ''}".lower()
        passed, failure = (res["sql"] is None and s.keyword in said), "meta_wrong"
        passed, failure = passed, None if passed else failure
        alts: list = []
    else:
        with psycopg.connect(db_url) as conn:
            alts = compute_truth(conn, s.final)
        passed, failure = grade(s.final, res, alts)
    return {"id": s.id, "category": s.final.category, "turns": len(s.turns), "question": s.turns[-1],
            "passed": passed, "failure": failure, "expected": [a[:5] for a in alts], "rows": res["rows"][:5],
            "sql": res["sql"], "assumptions": res["assumptions"], "answer": res["answer"],
            "error": res["error"], "input_tokens": res["input_tokens"], "latency_ms": res["latency_ms"]}


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", default="6", help="comma-separated memory_turns values to compare")
    ap.add_argument("--ids")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    db_url = os.environ.get("DATABASE_URL", "postgresql:///marginai")
    scenarios = [s for s in SCENARIOS if not args.ids or s.id in args.ids.split(",")]
    engine = Engine(GeminiClient(fallbacks=[]), db_url, log=False)
    out = {}
    for memory in [int(m) for m in args.memory.split(",")]:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(lambda s: run_scenario(engine, db_url, s, memory), scenarios))
        passed = sum(r["passed"] for r in rows)
        # the graded turn's prompt size, i.e. what memory adds to the cost of one question
        tok = sum(r["input_tokens"] for r in rows) / len(rows)
        print(f"\nmemory={memory}: {passed}/{len(rows)} correct; avg prompt tokens in graded turn's call(s) "
              f"{tok:,.0f}")
        for r in rows:
            if not r["passed"]:
                print(f"  FAIL {r['id']} ({r['category']}): {r['question']}\n"
                      f"       got {str(r['rows'])[:110]} | {str(r['assumptions'])[:130]}")
        out[memory] = {"passed": passed, "total": len(rows), "avg_input_tokens": round(tok), "results": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{engine.llm.model}.json"
    path.write_text(json.dumps({"model": engine.llm.model, "by_memory": out}, indent=1, default=str))
    print("Saved", path)


if __name__ == "__main__":
    main()

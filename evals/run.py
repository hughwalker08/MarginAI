"""Run the eval suite and save a timestamped result file in evals/results/.

  python -m evals.run                      # all questions, default model
  python -m evals.run --ids q01,q15        # specific questions
  python -m evals.run --difficulty hard
  python -m evals.run --model gemini-3.5-flash --workers 2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from backend.engine.engine import Engine
from backend.engine.executor import _json_safe
from backend.engine.llm import GeminiClient

from .grader import grade
from .questions import QUESTIONS, Q

RESULTS = Path(__file__).parent / "results"


def compute_truth(conn, q: Q) -> list[list[list]]:
    out = []
    for sql in q.truth:
        rows = conn.execute(sql).fetchall()
        out.append([[_json_safe(v) for v in r] for r in rows])
    return out


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).parents[1]).stdout.strip()
    except Exception:
        return ""


def run_one(engine: Engine, db_url: str, q: Q) -> dict:
    with psycopg.connect(db_url) as conn:
        alts = compute_truth(conn, q)
        n_before = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    res = engine.ask(q.question).to_dict()
    with psycopg.connect(db_url) as conn:
        intact = conn.execute("SELECT count(*) FROM orders").fetchone()[0] == n_before
    passed, failure = grade(q, res, alts, intact)
    return {
        "id": q.id, "difficulty": q.difficulty, "category": q.category, "question": q.question,
        "mode": q.mode, "passed": passed, "failure": failure, "first_attempt": passed and res["attempts"] == 1,
        "expected": [a[:10] for a in alts], "columns": res["columns"], "rows": res["rows"][:20],
        "sql": res["sql"], "answer": res["answer"], "assumptions": res["assumptions"],
        "clarification": res["clarification"], "error": res["error"], "attempts": res["attempts"],
        "latency_ms": res["latency_ms"], "input_tokens": res["input_tokens"],
        "output_tokens": res["output_tokens"], "cost_usd": res["cost_usd"], "model": res["model"],
    }


def summarise(results: list[dict]) -> dict:
    n = len(results)
    passed = sum(r["passed"] for r in results)
    lat = sorted(r["latency_ms"] for r in results)
    by = lambda key: {k: {"passed": sum(r["passed"] for r in g), "total": len(g)}
                      for k, g in _group(results, key).items()}
    return {
        "total": n, "passed": passed, "accuracy": round(passed / n, 4) if n else 0,
        "first_attempt_accuracy": round(sum(r["first_attempt"] for r in results) / n, 4) if n else 0,
        "by_difficulty": by("difficulty"), "by_category": by("category"),
        "failures": {k: len(g) for k, g in _group([r for r in results if not r["passed"]], "failure").items()},
        "latency_ms_mean": int(statistics.mean(lat)) if lat else 0,
        "latency_ms_p95": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0,
        "input_tokens": sum(r["input_tokens"] for r in results),
        "output_tokens": sum(r["output_tokens"] for r in results),
        "cost_usd": round(sum(r["cost_usd"] for r in results), 4),
        "cost_per_question_usd": round(sum(r["cost_usd"] for r in results) / n, 5) if n else 0,
    }


def _group(items: list[dict], key: str) -> dict[str, list[dict]]:
    g = defaultdict(list)
    for r in items:
        g[r[key]].append(r)
    return g


def print_summary(s: dict) -> None:
    print(f"\nAccuracy: {s['passed']}/{s['total']} = {s['accuracy']:.1%} "
          f"(first-attempt {s['first_attempt_accuracy']:.1%})")
    for k, v in s["by_difficulty"].items():
        print(f"  {k:8s} {v['passed']}/{v['total']}")
    if s["failures"]:
        print("Failures:", ", ".join(f"{k}={v}" for k, v in sorted(s["failures"].items())))
    print(f"Latency mean {s['latency_ms_mean']} ms, p95 {s['latency_ms_p95']} ms; "
          f"tokens {s['input_tokens']}+{s['output_tokens']}; cost ${s['cost_usd']:.4f}")


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--difficulty")
    ap.add_argument("--model")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--label", default="")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL", "postgresql:///marginai")
    qs = QUESTIONS
    if args.ids:
        wanted = set(args.ids.split(","))
        qs = [x for x in qs if x.id in wanted]
    if args.difficulty:
        qs = [x for x in qs if x.difficulty == args.difficulty]

    llm = GeminiClient(model=args.model)
    engine = Engine(llm, db_url, log=False)
    started = datetime.now(timezone.utc)
    done = 0

    def task(q: Q) -> dict:
        nonlocal done
        try:
            r = run_one(engine, db_url, q)
        except Exception as e:  # a harness failure must not lose the whole run
            r = {"id": q.id, "difficulty": q.difficulty, "category": q.category, "question": q.question,
                 "mode": q.mode, "passed": False, "failure": "harness_error", "first_attempt": False,
                 "error": f"{type(e).__name__}: {e}", "latency_ms": 0, "input_tokens": 0,
                 "output_tokens": 0, "cost_usd": 0.0, "model": llm.model, "attempts": 0}
        done += 1
        print(f"[{done}/{len(qs)}] {q.id} {'PASS' if r['passed'] else 'FAIL ' + str(r['failure'])} "
              f"({r['latency_ms']} ms)", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(task, qs))

    summary = summarise(results)
    print_summary(summary)
    if args.no_save:
        return
    run = {
        "run_id": started.strftime("%Y%m%dT%H%M%SZ"), "label": args.label, "model": llm.model,
        "fallbacks": llm.fallbacks, "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "prompt_hash": hashlib.sha256(engine.system.encode()).hexdigest()[:10],
        "partial": len(qs) < len(QUESTIONS), "summary": summary, "results": results,
    }
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{run['run_id']}_{llm.model}.json"
    path.write_text(json.dumps(run, indent=1, default=str))
    print("Saved", path)


if __name__ == "__main__":
    main()

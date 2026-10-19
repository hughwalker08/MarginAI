"""Are the suggested follow-up questions any good? Ask each eval question, then ask each suggestion it produced (with the
conversation so far) and see whether the engine can actually answer it.

  python -m evals.suggestion_check [--limit 57] [--workers 4]
Reports how many suggestions were answered with data, declined, empty, or failed, plus a sample to read.
"""
from __future__ import annotations

import argparse
import os
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from backend.engine.engine import Engine
from backend.engine.llm import GeminiClient

from .questions import QUESTIONS
from .run_followups import to_history


def check(engine: Engine, q) -> list[dict]:
    first = engine.ask(q.question).to_dict()
    history = [to_history(first)]
    rows = []
    for s in first["follow_ups"]:
        r = engine.ask(s, history=history).to_dict()
        if r["sql"] is None:
            verdict = "declined"
        elif r["error"] and not r["rows"]:
            verdict = "error"
        elif not r["rows"]:
            verdict = "empty"
        else:
            verdict = "answered"
        rows.append({"from": q.question, "suggestion": s, "verdict": verdict, "mode": q.mode})
    if not first["follow_ups"]:
        rows.append({"from": q.question, "suggestion": None, "verdict": "none", "mode": q.mode})
    return rows


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(QUESTIONS))
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    engine = Engine(GeminiClient(fallbacks=[]), os.environ.get("DATABASE_URL", "postgresql:///marginai"), log=False)
    qs = QUESTIONS[: args.limit]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = [r for rows in pool.map(lambda q: check(engine, q), qs) for r in rows]
    scored = [r for r in results if r["verdict"] != "none" and r["mode"] in ("cells", "rows")]
    c = Counter(r["verdict"] for r in scored)
    n = sum(c.values())
    print(f"\n{n} suggestions for {len(qs)} questions (those answerable from the data):")
    for k in ("answered", "empty", "declined", "error"):
        print(f"  {k:9s} {c[k]:4d}  {c[k] / n:6.1%}")
    no_sugg = [r["from"] for r in results if r["verdict"] == "none" and r["mode"] in ("cells", "rows")]
    print(f"  questions with no suggestions at all: {len(no_sugg)}")
    print("\nA sample to read:")
    for r in random.Random(1).sample(scored, min(14, len(scored))):
        print(f"  [{r['verdict']:8s}] {r['from'][:52]:52s} -> {r['suggestion']}")
    bad = [r for r in scored if r["verdict"] != "answered"]
    if bad:
        print("\nNot answered with data:")
        for r in bad[:15]:
            print(f"  [{r['verdict']}] {r['suggestion']}   (after: {r['from'][:45]})")


if __name__ == "__main__":
    main()

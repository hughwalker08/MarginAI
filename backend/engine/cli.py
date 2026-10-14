"""Ask a question from the command line.

  python -m backend.engine.cli "What sold best last weekend?"
  python -m backend.engine.cli            # interactive; blank line to quit
"""
import argparse
import os

from dotenv import load_dotenv

from .engine import Engine, EngineResult
from .llm import GeminiClient


def render(r: EngineResult, show_rows: int = 15) -> str:
    out = ["", r.answer, ""]
    if r.assumptions:
        out.append(f"Assumptions: {r.assumptions}\n")
    if r.rows:
        widths = [max(len(str(c)), *(len(str(row[i])) for row in r.rows[:show_rows]))
                  for i, c in enumerate(r.columns)]
        out.append("  ".join(str(c).ljust(w) for c, w in zip(r.columns, widths)))
        out += ["  ".join(str(v).ljust(w) for v, w in zip(row, widths)) for row in r.rows[:show_rows]]
        if len(r.rows) > show_rows:
            out.append(f"... {len(r.rows) - show_rows} more rows")
        out.append("")
    if r.sql:
        out += ["SQL:", r.sql, ""]
    if r.chart:
        out.append(f"Chart: {r.chart}")
    out.append(f"[{r.model}] {r.attempts} attempt(s), {r.latency_ms} ms, "
               f"{r.input_tokens}+{r.output_tokens} tokens, ~${r.cost_usd:.4f}"
               + (f", ERROR: {r.error}" if r.error else ""))
    return "\n".join(out)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--model")
    args = ap.parse_args()
    engine = Engine(GeminiClient(model=args.model), os.environ.get("DATABASE_URL", "postgresql:///marginai"))
    if args.question:
        print(render(engine.ask(args.question)))
        return
    while q := input("\nAsk> ").strip():
        print(render(engine.ask(q)))


if __name__ == "__main__":
    main()

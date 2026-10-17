"""Show every saved eval run side by side: python -m evals.history

Summaries are recomputed from each run's per-question results, so older runs are scored under the
current rules (e.g. provider outages excluded from accuracy)."""
import json
from pathlib import Path

from .run import summarise

RESULTS = Path(__file__).parent / "results"


def main() -> None:
    runs = [json.loads(p.read_text()) for p in sorted(RESULTS.glob("*.json"))]
    if not runs:
        print("No runs yet. Run: python -m evals.run")
        return
    print(f"{'run':17s} {'model':24s} {'commit':8s} {'prompt':10s} {'acc':>6s} {'1st':>6s} {'scored':>7s} "
          f"{'easy':>6s} {'med':>6s} {'hard':>6s} {'ms':>7s} {'$/q':>8s}  label")
    for r in runs:
        s = summarise(r["results"])
        d = s["by_difficulty"]
        frac = lambda k: f"{d[k]['passed']}/{d[k]['total']}" if k in d else "-"
        print(f"{r['run_id']:17s} {r['model']:24s} {r['git_commit']:8s} {r['prompt_hash']:10s} "
              f"{s['accuracy']:6.1%} {s['first_attempt_accuracy']:6.1%} {s['scored']:>3d}/{s['total']:<3d} "
              f"{frac('easy'):>6s} {frac('medium'):>6s} {frac('hard'):>6s} {s['latency_ms_mean']:7d} "
              f"{s['cost_per_question_usd']:8.5f}  {r['label']}{' (partial)' if r.get('partial') else ''}")


if __name__ == "__main__":
    main()

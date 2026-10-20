"""Pick a chart type from the shape of a result set (deterministic, no LLM call)."""
from __future__ import annotations

import datetime as dt
import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?")


def _is_id(name: str) -> bool:
    """customer_id, order_id, id: identifiers, never something to chart."""
    n = name.lower()
    return n == "id" or n.endswith("_id") or n.endswith("_number") and n.startswith("order")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_date(v) -> bool:
    return isinstance(v, (dt.date, dt.datetime)) or (isinstance(v, str) and bool(_DATE_RE.match(v)))


def suggest_chart(columns: list[str], rows: list[list]) -> dict | None:
    """Return {"type": line|bar|table-only..., "x": col, "y": [cols], "series": col?} or None."""
    if len(rows) < 2 or len(columns) < 2:
        return None
    # First non-null value per column, so a leading NULL (e.g. LAG) doesn't hide a numeric column.
    sample = [next((r[i] for r in rows if r[i] is not None), None) for i in range(len(columns))]
    num = [i for i, v in enumerate(sample) if _is_num(v) and not _is_id(columns[i])]
    non_num = [i for i, v in enumerate(sample) if v is not None and not _is_num(v)]
    if not num or not non_num:
        return None
    x = non_num[0]
    if _is_date(sample[x]):
        kind = "line"
    elif len(rows) <= 30:
        kind = "bar"
        labels = [r[x] for r in rows]
        if len(set(labels)) < len(labels):
            # The same label on several rows (e.g. the top products PER store). That only charts as grouped bars when
            # one measure is split by a second category with a few values; otherwise the table is the clearer view.
            grouped = len(non_num) > 1 and len(num) == 1 and len({r[non_num[1]] for r in rows}) <= 6
            if not grouped:
                return None
    else:
        return None
    chart = {"type": kind, "x": columns[x], "y": [columns[i] for i in num][:3]}
    if len(non_num) > 1 and len(num) == 1 and kind in ("line", "bar"):
        chart["series"] = columns[non_num[1]]
    return chart

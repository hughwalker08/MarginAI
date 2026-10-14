"""Run validated SQL under the read-only role with a timeout and row cap."""
from __future__ import annotations

import datetime as dt
import decimal
from dataclasses import dataclass

import psycopg

READONLY_ROLE = "marginai_readonly"
MAX_ROWS = 500
TIMEOUT = "10s"


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool = False


def _json_safe(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    return v


def run_readonly(database_url: str, sql: str, max_rows: int = MAX_ROWS) -> QueryResult:
    with psycopg.connect(database_url) as conn:
        try:
            conn.execute("BEGIN READ ONLY")
            conn.execute(f"SET LOCAL ROLE {READONLY_ROLE}")
            conn.execute(f"SET LOCAL statement_timeout = '{TIMEOUT}'")
            conn.execute("SET LOCAL TIME ZONE 'Australia/Sydney'")
            cur = conn.execute(sql)
            columns = [d.name for d in cur.description]
            fetched = cur.fetchmany(max_rows + 1)
        finally:
            conn.rollback()
    return QueryResult(columns, [[_json_safe(v) for v in r] for r in fetched[:max_rows]],
                       truncated=len(fetched) > max_rows)

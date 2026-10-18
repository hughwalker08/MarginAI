"""Run validated SQL under the read-only role with a timeout and row cap."""
from __future__ import annotations

import datetime as dt
import decimal
import re
from dataclasses import dataclass

import psycopg

READONLY_ROLE = "marginai_readonly"
_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_TZ = re.compile(r"^[A-Za-z]+(/[A-Za-z_\-+0-9]+){0,2}$")
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


def run_readonly(database_url: str, sql: str, max_rows: int = MAX_ROWS, role: str = READONLY_ROLE,
                 schema: str = "public", timezone: str = "Australia/Sydney") -> QueryResult:
    """Run `sql` as `role`, which can see only `schema` (the store being queried). The role and schema
    names come from our own stores table, never from user input; they are re-checked here anyway."""
    for ident in (role, schema):
        if not _IDENT.match(ident):
            raise ValueError(f"unsafe identifier: {ident!r}")
    if not _TZ.match(timezone):
        raise ValueError(f"unsafe timezone: {timezone!r}")
    with psycopg.connect(database_url) as conn:
        try:
            conn.execute("BEGIN READ ONLY")
            conn.execute(f'SET LOCAL ROLE "{role}"')
            conn.execute(f'SET LOCAL search_path TO "{schema}"')
            conn.execute(f"SET LOCAL statement_timeout = '{TIMEOUT}'")
            conn.execute(f"SET LOCAL TIME ZONE '{timezone}'")
            cur = conn.execute(sql)
            columns = [d.name for d in cur.description]
            fetched = cur.fetchmany(max_rows + 1)
        finally:
            conn.rollback()
    return QueryResult(columns, [[_json_safe(v) for v in r] for r in fetched[:max_rows]],
                       truncated=len(fetched) > max_rows)

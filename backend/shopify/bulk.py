"""Run a query as a Shopify bulk operation and stream back its JSONL result."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator

import httpx

from . import oauth

START = """
mutation($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""
POLL = "{ currentBulkOperation(type: QUERY) { id status errorCode objectCount url partialDataUrl } }"


class BulkError(RuntimeError):
    pass


def run_bulk(shop: str, token: str, query: str, poll_seconds: float = 2.0, timeout_s: float = 1800,
             sleep=time.sleep) -> Iterator[dict]:
    """Start the bulk query (waiting if another is still running), wait for it, then yield each JSONL line."""
    deadline = time.monotonic() + timeout_s
    while True:
        started = oauth.graphql(shop, token, START, {"query": query})["bulkOperationRunQuery"]
        errors = started.get("userErrors") or []
        if not errors:
            break
        if any("already in progress" in (e.get("message") or "").lower() for e in errors):
            if time.monotonic() > deadline:
                raise BulkError("Another bulk operation kept running; gave up waiting")
            sleep(max(poll_seconds, 5))
            continue
        raise BulkError(f"Shopify rejected the bulk query: {errors}")
    op_id = started["bulkOperation"]["id"]

    while True:
        cur = oauth.graphql(shop, token, POLL)["currentBulkOperation"]
        if cur and cur["id"] == op_id:
            if cur["status"] == "COMPLETED":
                return _download(cur.get("url"))
            if cur["status"] in ("FAILED", "CANCELED", "EXPIRED"):
                raise BulkError(f"Bulk operation {cur['status']} ({cur.get('errorCode')})")
        if time.monotonic() > deadline:
            raise BulkError("Bulk operation timed out")
        sleep(poll_seconds)


def _download(url: str | None) -> Iterator[dict]:
    if not url:  # no matching objects
        return iter(())
    def lines() -> Iterator[dict]:
        with httpx.stream("GET", url, timeout=120) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.strip():
                    yield json.loads(line)
    return lines()

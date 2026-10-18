import os

import psycopg
import pytest

from backend.engine import catalogue, context
from backend.engine.engine import Engine
from backend.engine.llm import FakeLLM
from backend.stores import DEMO

DB = os.environ.get("DATABASE_URL", "postgresql:///marginai")


def test_search_terms_drop_filler_singularise_and_expand_colours():
    t = catalogue.search_terms("How have sales of the cotton blue dress shirts changed over the last 3 months?")
    assert "cotton" in t and "dress" in t and "shirt" in t and "navy" in t and "cobalt" in t  # blue -> its family
    assert not {"sales", "last", "how", "the", "shirts"} & set(t)
    assert catalogue.search_terms("what is our revenue?") == []
    assert "category" in catalogue.search_terms("categories")


def _db_ready() -> bool:
    try:
        with psycopg.connect(DB) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


needs_db = pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")


@needs_db
def test_find_products_ranks_by_matched_terms():
    with psycopg.connect(DB) as conn:
        rows = catalogue.find_products(conn, "blue shirt", k=5)
    titles = [r[0] for r in rows]
    assert "Linen Shirt" in titles[:2]  # Navy colour (blue family) + 'shirt' in title
    assert catalogue.hint(DB, DEMO, "what is our revenue?") == ""


@needs_db
def test_search_mode_summarises_the_catalogue_and_attaches_matches(monkeypatch):
    monkeypatch.setattr(context, "FULL_MAX", 0)
    ctx = context.build_store_context(DB, DEMO)
    assert ctx.search_mode and "too many to list" in ctx.text and "Best sellers" in ctx.text
    assert "Linen Wrap Dress |" not in ctx.text  # the per-product list is gone
    llm = FakeLLM(['{"sql": "SELECT 1 AS x FROM orders LIMIT 1", "assumptions": "", "clarification": null}', "ok"])
    e = Engine(llm, DB, log=False)
    assert e.search_catalogue
    e.ask("How have sales of the blue shirt changed?")
    sent = llm.calls[0][1][-1].text
    assert "Catalogue entries that may match" in sent and "Linen Shirt" in sent


@needs_db
def test_full_listing_is_used_for_small_catalogues():
    ctx = context.build_store_context(DB, DEMO)
    assert not ctx.search_mode and "Linen Shirt | top | Navy, Stripe" in ctx.text

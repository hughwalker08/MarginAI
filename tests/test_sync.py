"""The sync, tested end to end on Shopify-shaped fixtures (no network)."""
import os
from decimal import Decimal

import psycopg
import pytest

from backend.engine.executor import run_readonly
from backend.shopify import mapping, queries, sync
from backend.stores import create_store

DB = os.environ.get("DATABASE_URL", "postgresql:///marginai")
SHOP = "zz-sync.myshopify.com"


def m(x):
    return {"shopMoney": {"amount": str(x)}}


PRODUCTS = [
    {"id": "gid://shopify/Product/9000000000001", "title": "Linen Shirt", "productType": "Tops", "vendor": "Saarde",
     "status": "ACTIVE", "createdAt": "2026-01-01T00:00:00Z"},
    {"id": "gid://shopify/ProductVariant/9100000000001", "__parentId": "gid://shopify/Product/9000000000001",
     "sku": "LS-S", "price": "120.00", "selectedOptions": [{"name": "Size", "value": "S"}, {"name": "Colour", "value": "Navy"}],
     "inventoryItem": {"unitCost": {"amount": "40.00"}}},
    {"id": "gid://shopify/ProductVariant/9100000000002", "__parentId": "gid://shopify/Product/9000000000001",
     "sku": "LS-M", "price": "120.00", "selectedOptions": [{"name": "Size", "value": "M"}], "inventoryItem": {"unitCost": None}},
]
LOCATIONS = [{"id": "gid://shopify/Location/1", "name": "Redfern", "isActive": True},
             {"id": "gid://shopify/Location/2", "name": "Rosebery", "isActive": True}]


def order(n, created, status="PAID", source="web", location=None, customer="gid://shopify/Customer/5", cancelled=None,
          test=False, total="120.00", discount=None):
    o = {"id": f"gid://shopify/Order/{8000000000000 + n}", "name": f"#{1000 + n}", "createdAt": created,
         "cancelledAt": cancelled, "test": test, "displayFinancialStatus": status, "sourceName": source,
         "retailLocation": {"id": location} if location else None, "customer": {"id": customer} if customer else None,
         "subtotalPriceSet": m(total), "totalDiscountsSet": m("0.00"), "totalShippingPriceSet": m("0.00"),
         "totalTaxSet": m("10.91"), "totalPriceSet": m(total), "refunds": []}
    return o


def lines_for(o, variant="gid://shopify/ProductVariant/9100000000001", qty=1, price="120.00", li=1):
    return {"id": f"gid://shopify/LineItem/{7000000000000 + int(o['id'][-4:]) * 10 + li}", "__parentId": o["id"],
            "quantity": qty, "originalUnitPriceSet": m(price), "totalDiscountSet": m("0.00"),
            "variant": {"id": variant} if variant else None}


def first_run_orders():
    o1 = order(1, "2026-10-01T02:00:00Z")  # online
    o2 = order(2, "2026-10-02T03:00:00Z", source="pos", location="gid://shopify/Location/1", total="240.00")
    o3 = order(3, "2026-10-03T03:00:00Z", test=True)  # test order: must be dropped
    o4 = order(4, "2026-10-04T03:00:00Z", source="pos", location="gid://shopify/Location/2", customer=None)
    disc = {"__typename": "DiscountCodeApplication", "allocationMethod": "ACROSS", "targetType": "LINE_ITEM",
            "code": "WELCOME10", "value": {"__typename": "PricingPercentageValue", "percentage": 10.0}, "__parentId": o1["id"]}
    return [o1, lines_for(o1), disc, o2, lines_for(o2, qty=2), o3, lines_for(o3), o4,
            lines_for(o4, variant="gid://shopify/ProductVariant/9999999999999")]  # unknown variant


def second_run_orders():
    o1 = order(1, "2026-10-01T02:00:00Z", status="PARTIALLY_REFUNDED")
    o1["refunds"] = [{"id": "gid://shopify/Refund/6000000000001", "createdAt": "2026-10-05T00:00:00Z", "note": "Wrong size",
                      "totalRefundedSet": m("120.00"), "refundLineItems": None}]
    li = lines_for(o1)
    rl = {"id": "gid://shopify/RefundLineItem/6100000000001", "__parentId": "gid://shopify/Refund/6000000000001",
          "quantity": 1, "restockType": "RETURN", "subtotalSet": m("120.00"), "lineItem": {"id": li["id"]}}
    o2 = order(2, "2026-10-02T03:00:00Z", source="pos", location="gid://shopify/Location/1", cancelled="2026-10-06T00:00:00Z")
    return [o1, li, rl, o2, lines_for(o2, qty=2)]


def fetcher(products, orders):
    def fetch(query):
        return iter(products if "products" in query.split("{")[1] else orders)
    return fetch


def _db_ready() -> bool:
    try:
        with psycopg.connect(DB) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


needs_db = pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")


@pytest.fixture()
def store():
    s = create_store(DB, "zz_sync", "Zz Sync Shop", SHOP)
    yield s
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("DELETE FROM stores WHERE slug = 'zz_sync'")
        c.execute('DROP SCHEMA IF EXISTS "store_zz_sync" CASCADE')
        c.execute('DROP OWNED BY "ro_zz_sync"')
        c.execute('DROP ROLE IF EXISTS "ro_zz_sync"')


def q(sql):
    return run_readonly(DB, sql, role="ro_zz_sync", schema="store_zz_sync").rows


def test_mapping_basics():
    assert mapping.gid("gid://shopify/Order/123?key=x") == 123 and mapping.gid(None) is None
    assert mapping.map_status("PAID", None) == "paid" and mapping.map_status("PAID", "2026-01-01T00:00:00Z") == "voided"
    assert mapping.map_status("PENDING", None) == "paid" and mapping.map_status("REFUNDED", None) == "refunded"
    batch = mapping.parse_orders(first_run_orders())
    assert [o["order_number"] for o in batch.orders] == [1001, 1002, 1004]  # the test order is gone
    by = {o["order_number"]: o for o in batch.orders}
    assert by[1001]["sales_channel"] == "online" and by[1001]["location_id"] == mapping.ONLINE_LOCATION_ID
    assert by[1002]["sales_channel"] == "pos" and by[1002]["location_id"] == 1 and by[1004]["customer_id"] is None
    assert len(batch.discounts) == 1 and next(iter(batch.discounts.values()))["kind"] == "percentage"
    p = mapping.parse_products(PRODUCTS)
    assert p.variants[0]["color"] == "Navy" and p.variants[0]["size"] == "S" and p.variants[0]["cost"] == Decimal("40.00")
    assert p.variants[1]["cost"] is None and p.variants[1]["color"] is None


def test_orders_query_is_valid_looking_and_incremental():
    assert "updated_at:>=2026-01-01T00:00:00Z" in queries.orders("2026-01-01T00:00:00Z")
    assert "updated_at" not in queries.orders()
    assert "provinceCode" in queries.orders(addresses=True) and "provinceCode" not in queries.orders()


@needs_db
def test_full_then_incremental_sync(store):
    r = sync.sync_store(DB, "zz_sync", fetch=fetcher(PRODUCTS, first_run_orders()), locations=LOCATIONS)
    assert r["mode"] == "full" and r["orders"] == 3
    assert q("SELECT count(*) FROM orders") == [[3]]
    assert q("SELECT name FROM locations ORDER BY name") == [["Online Store"], ["Redfern"], ["Rosebery"], ["Unknown location"]]
    # order 4's variant is not in the catalogue: the line falls back to the placeholder instead of breaking the FK
    assert q("SELECT count(*) FROM order_lines l JOIN variants v USING (variant_id) WHERE v.variant_id = 0") == [[1]]
    assert q("SELECT code, kind, value FROM discounts") == [["WELCOME10", "percentage", 10.0]]
    # the question the engine would write works against the synced data
    assert q("SELECT round(sum(total), 2) FROM orders WHERE financial_status <> 'voided'") == [[480.0]]
    with psycopg.connect(DB) as c:
        assert c.execute("SELECT last_synced_at FROM stores WHERE slug = 'zz_sync'").fetchone()[0] is not None

    # a second run only sees changed orders: a refund on #1001 and #1002 cancelled
    r2 = sync.sync_store(DB, "zz_sync", fetch=fetcher([], second_run_orders()), locations=LOCATIONS)
    assert r2["mode"] == "incremental" and r2["orders"] == 2 and r2["refunds"] == 1
    assert q("SELECT financial_status FROM orders WHERE order_number = 1001") == [["partially_refunded"]]
    assert q("SELECT financial_status FROM orders WHERE order_number = 1002") == [["voided"]]
    assert q("SELECT count(*) FROM orders") == [[3]]  # nothing duplicated
    assert q("SELECT count(*) FROM order_lines") == [[3]]  # lines were replaced, not doubled
    assert q("SELECT r.amount, r.reason, r.restocked, rl.quantity FROM refunds r JOIN refund_lines rl USING (refund_id)") \
        == [[120.0, "Wrong size", True, 1]]
    with psycopg.connect(DB) as c:
        log = c.execute("SELECT mode, status, orders_synced FROM sync_log WHERE store_slug = 'zz_sync' ORDER BY log_id").fetchall()
    assert log == [("full", "ok", 3), ("incremental", "ok", 2)]


@needs_db
def test_failed_sync_rolls_back_and_is_logged(store):
    def boom(query):
        if "products" in query.split("{")[1]:
            return iter(PRODUCTS)
        raise RuntimeError("shopify exploded")

    with pytest.raises(RuntimeError):
        sync.sync_store(DB, "zz_sync", fetch=boom, locations=LOCATIONS)
    assert q("SELECT count(*) FROM orders") == [[0]]
    with psycopg.connect(DB) as c:
        assert c.execute("SELECT status, error FROM sync_log WHERE store_slug = 'zz_sync'").fetchone()[0] == "error"
        assert c.execute("SELECT last_synced_at FROM stores WHERE slug = 'zz_sync'").fetchone()[0] is None


@needs_db
def test_concurrent_sync_is_refused(store):
    holder = psycopg.connect(DB, autocommit=True)
    try:
        holder.execute("SELECT pg_advisory_lock(hashtext('marginai_sync_zz_sync'))")
        with pytest.raises(sync.SyncBusy):
            sync.sync_store(DB, "zz_sync", fetch=fetcher(PRODUCTS, []), locations=LOCATIONS)
    finally:
        holder.close()


@needs_db
def test_sync_refuses_the_demo_store():
    with pytest.raises(ValueError):
        sync.sync_store(DB, "demo")


def test_scheduler_runs_rounds_and_survives_failures(monkeypatch):
    import threading

    from backend.shopify.scheduler import SyncScheduler

    calls, done = [], threading.Event()

    def fake_sync_all(db):
        calls.append(db)
        if len(calls) == 1:
            raise RuntimeError("first round fails")
        done.set()
        return []

    monkeypatch.setattr(sync, "sync_all", fake_sync_all)
    sched = SyncScheduler("db", interval_minutes=0.001, first_delay_s=0.01)  # ~60 ms between rounds
    sched.start()
    assert done.wait(5), "scheduler stopped after a failed round"
    sched.stop()
    assert len(calls) >= 2


@needs_db
def test_live_store_engine_rebuilds_its_context_and_lists_last_sync(store, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from backend import api
    from backend.engine.engine import Engine
    from backend.engine.llm import FakeLLM

    sync.sync_store(DB, "zz_sync", fetch=fetcher(PRODUCTS, first_run_orders()), locations=LOCATIONS)
    monkeypatch.setattr(api, "GeminiClient", lambda: None)
    reply = json.dumps({"sql": "SELECT count(*) AS n FROM orders", "assumptions": "", "clarification": None})
    monkeypatch.setattr(api, "Engine", lambda llm, url, **kw: Engine(FakeLLM([reply, "ok"] * 5), url, log=False, **kw))
    with TestClient(api.app) as c:
        listed = {s["slug"]: s for s in c.get("/api/stores").json()}
        assert listed["zz_sync"]["last_synced_at"] and listed["demo"]["last_synced_at"] is None
        assert len(c.get("/api/examples", params={"store": "zz_sync"}).json()) >= 6
        assert c.get("/api/examples").json() != c.get("/api/examples", params={"store": "zz_sync"}).json()
        first = api.engine_for("zz_sync")
        assert first.store.live and "Today is" in first.system  # a live store uses the real date
        built = first.context_built_at
        monkeypatch.setattr(api, "CONTEXT_TTL_SECONDS", 0)
        api.engine_for("zz_sync")
        assert first.context_built_at > built  # stale context was rebuilt
        assert "Treat" in api.engine_for("demo").system  # the demo keeps its frozen date

"""Pull a connected store's data from Shopify into its schema.

  python -m backend.shopify.sync --store saarde            # incremental (full the first time)
  python -m backend.shopify.sync --store saarde --full     # re-read everything
  python -m backend.shopify.sync --all --loop 15           # every connected store, every 15 minutes

Incremental runs ask Shopify only for orders and products changed since the last run (with a 10 minute overlap),
then replace those orders' lines and refunds, so edits, refunds and cancellations come through.
"""
from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone

import psycopg

from ..stores import Store, get_store, list_stores
from . import bulk, mapping, oauth, queries, vault

OVERLAP = timedelta(minutes=10)
Fetch = Callable[[str], Iterable[dict]]


class SyncBusy(RuntimeError):
    pass


def _copy_in(conn: psycopg.Connection, table: str, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row([r[c] for c in cols])


def _upsert(conn: psycopg.Connection, table: str, pk: str, cols: list[str], rows: list[dict],
            update_sql: str | None = None) -> None:
    """COPY into a temp table, then INSERT .. ON CONFLICT so existing rows are refreshed."""
    if not rows:
        return
    conn.execute(f"CREATE TEMP TABLE _stage (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    _copy_in(conn, "_stage", cols, rows)
    sets = update_sql or ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != pk)
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _stage "
                 f"ON CONFLICT ({pk}) DO UPDATE SET {sets}")
    conn.execute("DROP TABLE _stage")


def _existing(conn: psycopg.Connection, table: str, pk: str, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return {r[0] for r in conn.execute(f"SELECT {pk} FROM {table} WHERE {pk} = ANY(%s)", (ids,))}


def default_fetch(database_url: str, store: Store) -> Fetch:
    def fetch(query: str) -> Iterable[dict]:
        token = vault.get_access_token(database_url, store.slug, store.shop_domain or "")
        return bulk.run_bulk(store.shop_domain or "", token, query)
    return fetch


def sync_store(database_url: str, slug: str, full: bool = False, fetch: Fetch | None = None,
               locations: list[dict] | None = None) -> dict:
    store = get_store(database_url, slug)
    if store is None or not store.shop_domain:
        raise ValueError(f"{slug!r} is not a connected Shopify store")
    started = datetime.now(timezone.utc)
    lock = psycopg.connect(database_url, autocommit=True)  # holds the advisory lock for the whole run
    try:
        if not lock.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"marginai_sync_{slug}",)).fetchone()[0]:
            raise SyncBusy(f"A sync of {slug} is already running")
        with psycopg.connect(database_url) as c:
            last = c.execute("SELECT last_synced_at FROM stores WHERE slug = %s", (slug,)).fetchone()[0]
            mode = "full" if (full or last is None) else "incremental"
            log_id = c.execute("INSERT INTO sync_log (store_slug, mode) VALUES (%s, %s) RETURNING log_id",
                               (slug, mode)).fetchone()[0]
        since = None if mode == "full" else (last - OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            fetch = fetch or default_fetch(database_url, store)
            if locations is None:
                token = vault.get_access_token(database_url, slug, store.shop_domain)
                locs = oauth.graphql(store.shop_domain, token, queries.LOCATIONS)["locations"]["edges"]
                locations = [e["node"] for e in locs]
            prods = mapping.parse_products(fetch(queries.products(since)))
            orders = mapping.parse_orders(fetch(queries.orders(
                since, addresses=os.environ.get("SHOPIFY_SYNC_ADDRESSES") == "1")))
            n = _load(database_url, store, prods, orders, locations)
            with psycopg.connect(database_url, autocommit=True) as c:
                c.execute("UPDATE stores SET last_synced_at = %s WHERE slug = %s", (started, slug))
                c.execute("UPDATE sync_log SET status = 'ok', finished_at = now(), orders_synced = %s "
                          "WHERE log_id = %s", (n, log_id))
        except Exception as e:
            with psycopg.connect(database_url, autocommit=True) as c:
                c.execute("UPDATE sync_log SET status = 'error', finished_at = now(), error = %s WHERE log_id = %s",
                          (f"{type(e).__name__}: {e}"[:1000], log_id))
            raise
        return {"store": slug, "mode": mode, "orders": n, "products": len(prods.products),
                "variants": len(prods.variants), "refunds": len(orders.refunds)}
    finally:
        lock.close()


def _load(database_url: str, store: Store, prods: mapping.ProductBatch, orders: mapping.OrderBatch,
          locations: list[dict]) -> int:
    """Write everything in one transaction so questions never see a half-synced store."""
    with psycopg.connect(database_url) as conn:
        conn.execute(f'SET LOCAL search_path TO "{store.schema}"')
        conn.execute("INSERT INTO locations VALUES (%s, 'Online Store', 'online') ON CONFLICT DO NOTHING",
                     (mapping.ONLINE_LOCATION_ID,))
        conn.execute("INSERT INTO locations VALUES (%s, 'Unknown location', 'pos') ON CONFLICT DO NOTHING",
                     (mapping.UNKNOWN_POS_LOCATION_ID,))
        conn.execute("INSERT INTO products VALUES (%s, 'Custom item', NULL, NULL, 'active', now()) ON CONFLICT DO NOTHING",
                     (mapping.NO_VARIANT_ID,))
        conn.execute("INSERT INTO variants (variant_id, product_id, sku, price) VALUES (%s, %s, '', 0) "
                     "ON CONFLICT DO NOTHING", (mapping.NO_VARIANT_ID, mapping.NO_VARIANT_ID))

        loc_rows = [{"location_id": mapping.gid(x["id"]), "name": x["name"], "type": "pos"}
                    for x in locations if x.get("isActive", True)]
        _upsert(conn, "locations", "location_id", ["location_id", "name", "type"], loc_rows)
        _upsert(conn, "products", "product_id",
                ["product_id", "title", "product_type", "vendor", "status", "created_at"], prods.products)
        _upsert(conn, "variants", "variant_id",
                ["variant_id", "product_id", "sku", "size", "color", "price", "cost"], prods.variants)

        # Keep foreign keys valid: a deleted variant or location becomes a generic placeholder.
        have_variants = _existing(conn, "variants", "variant_id", [ln["variant_id"] for ln in orders.order_lines])
        for ln in orders.order_lines:
            if ln["variant_id"] not in have_variants:
                ln["variant_id"] = mapping.NO_VARIANT_ID
        have_locations = _existing(conn, "locations", "location_id", list({o["location_id"] for o in orders.orders}))
        for o in orders.orders:
            if o["location_id"] not in have_locations:
                o["location_id"] = mapping.UNKNOWN_POS_LOCATION_ID if o["sales_channel"] == "pos" else mapping.ONLINE_LOCATION_ID

        customers = [{"customer_id": c["customer_id"], "first_name": None, "last_name": None, "email": None,
                      "city": None, "state": None, "accepts_marketing": False, "created_at": c["created_at"]}
                     for c in orders.customers.values()]
        _upsert(conn, "customers", "customer_id",
                ["customer_id", "first_name", "last_name", "email", "city", "state", "accepts_marketing", "created_at"],
                customers, "created_at = LEAST(customers.created_at, EXCLUDED.created_at)")
        _upsert(conn, "discounts", "discount_id",
                ["discount_id", "code", "title", "kind", "value", "is_automatic", "starts_on", "ends_on"],
                list(orders.discounts.values()),
                "code = EXCLUDED.code, title = EXCLUDED.title, kind = EXCLUDED.kind, value = EXCLUDED.value, "
                "starts_on = LEAST(discounts.starts_on, EXCLUDED.starts_on)")

        ids = orders.order_ids
        if ids:  # replace the changed orders' children wholesale so edits, refunds and cancellations come through
            conn.execute("DELETE FROM refund_lines WHERE refund_id IN (SELECT refund_id FROM refunds WHERE order_id = ANY(%s))", (ids,))
            conn.execute("DELETE FROM refunds WHERE order_id = ANY(%s)", (ids,))
            conn.execute("DELETE FROM order_lines WHERE order_id = ANY(%s)", (ids,))
        _upsert(conn, "orders", "order_id",
                ["order_id", "order_number", "customer_id", "location_id", "sales_channel", "discount_id", "created_at",
                 "financial_status", "subtotal", "discount_total", "shipping_total", "tax_total", "total", "shipping_state"],
                orders.orders)
        _copy_in(conn, "order_lines", ["order_line_id", "order_id", "variant_id", "quantity", "unit_price", "line_discount"],
                 orders.order_lines)
        _copy_in(conn, "refunds", ["refund_id", "order_id", "created_at", "reason", "restocked", "amount"], orders.refunds)
        known_lines = {ln["order_line_id"] for ln in orders.order_lines}
        _copy_in(conn, "refund_lines", ["refund_line_id", "refund_id", "order_line_id", "quantity", "amount"],
                 [r for r in orders.refund_lines if r["order_line_id"] in known_lines])
        conn.commit()
    return len(orders.orders)


def sync_all(database_url: str, full: bool = False) -> list[dict]:
    results = []
    for store in list_stores(database_url):
        if not store.live:
            continue
        try:
            results.append(sync_store(database_url, store.slug, full=full))
        except SyncBusy:
            results.append({"store": store.slug, "skipped": "already running"})
        except Exception as e:  # one broken store must not stop the others
            results.append({"store": store.slug, "error": f"{type(e).__name__}: {e}"})
    return results


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--store")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--loop", type=float, metavar="MINUTES", help="repeat forever at this interval")
    args = ap.parse_args()
    if not (args.store or args.all):
        ap.error("give --store NAME or --all")
    db = os.environ.get("DATABASE_URL", "postgresql:///marginai")
    while True:
        out = sync_all(db, args.full) if args.all else [sync_store(db, args.store, full=args.full)]
        for r in out:
            print(r, flush=True)
        if not args.loop:
            break
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()

"""Stores: the synthetic demo plus any connected Shopify stores, each isolated in its own schema + role."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{2,29}$")
SCHEMA_SQL = Path(__file__).parents[1] / "db" / "migrations" / "001_schema.sql"


@dataclass(frozen=True)
class Store:
    slug: str
    name: str
    schema: str  # Postgres schema holding this store's tables
    role: str  # read-only role that can see only that schema
    timezone: str = "Australia/Sydney"
    currency: str = "AUD"
    tax_name: str = "GST"
    tax_divisor: float = 1.1  # price / divisor = price excluding tax
    shop_domain: str | None = None
    last_synced_at: datetime | None = None

    @property
    def live(self) -> bool:
        """Connected to a real shop, so \"today\" is the real date. The demo's data is frozen at a fixed date."""
        return self.shop_domain is not None


DEMO = Store("demo", "Willow & Finch", "public", "marginai_readonly")


def _from_row(r) -> Store:
    return Store(slug=r[0], name=r[1], schema=r[2], role=r[3], timezone=r[4], currency=r[5], tax_name=r[6],
                 tax_divisor=float(r[7]), shop_domain=r[8], last_synced_at=r[9])


_COLS = "slug, name, schema_name, role_name, timezone, currency, tax_name, tax_divisor, shop_domain, last_synced_at"


def get_store(database_url: str, slug: str) -> Store | None:
    if slug == DEMO.slug:
        return DEMO
    with psycopg.connect(database_url) as conn:
        row = conn.execute(f"SELECT {_COLS} FROM stores WHERE slug = %s", (slug,)).fetchone()
    return _from_row(row) if row else None


def list_stores(database_url: str, include_real: bool = True) -> list[Store]:
    stores = [DEMO]
    if include_real:
        with psycopg.connect(database_url) as conn:
            stores += [_from_row(r) for r in conn.execute(f"SELECT {_COLS} FROM stores ORDER BY name")]
    return stores


def create_store(database_url: str, slug: str, name: str, shop_domain: str | None = None,
                 timezone: str = "Australia/Sydney", currency: str = "AUD") -> Store:
    """Register a store and create its isolated schema and read-only role (idempotent)."""
    if not SLUG_RE.match(slug) or slug == DEMO.slug:
        raise ValueError(f"invalid store slug: {slug!r}")
    schema, role = f"store_{slug}", f"ro_{slug}"
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "INSERT INTO stores (slug, name, shop_domain, schema_name, role_name, timezone, currency) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (slug) DO UPDATE SET "
            "name = EXCLUDED.name, shop_domain = EXCLUDED.shop_domain, timezone = EXCLUDED.timezone, "
            "currency = EXCLUDED.currency", (slug, name, shop_domain, schema, role, timezone, currency))
        # Identifiers come from the validated slug above, never from user input directly.
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        if not conn.execute("SELECT to_regclass(%s)", (f"{schema}.orders",)).fetchone()[0]:
            conn.execute(f'SET LOCAL search_path TO "{schema}"')
            conn.execute(SCHEMA_SQL.read_text().replace(" integer", " bigint"))  # Shopify ids exceed 32 bits
            conn.execute("SET LOCAL search_path TO public")
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            conn.execute(f'CREATE ROLE "{role}" NOLOGIN')
        conn.execute(f'GRANT "{role}" TO CURRENT_USER')  # lets the app SET ROLE to it (needed on hosted Postgres)
        conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        conn.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"')
        conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON TABLES TO "{role}"')
        conn.execute(f'ALTER ROLE "{role}" SET default_transaction_read_only = on')
        conn.execute(f'ALTER ROLE "{role}" SET statement_timeout = \'10s\'')
        conn.commit()
    return get_store(database_url, slug)  # type: ignore[return-value]

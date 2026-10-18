"""Build the store-specific part of the prompt: what this particular store sells.

The schema description says how the data is shaped; this says what is in it, so the model can
map loose wording ("the blue shirt dress") onto real products, colours and codes.
"""
from __future__ import annotations

from pathlib import Path

import psycopg

from ..stores import DEMO, Store

SCHEMA_DESCRIPTION = Path(__file__).parents[2] / "db" / "schema_description.md"


def build_store_context(database_url: str, store: Store = DEMO) -> tuple[str, str]:
    """Return (store_context_text, data_as_of_date) for one store."""
    with psycopg.connect(database_url) as conn:
        conn.execute(f'SET search_path TO "{store.schema}"')  # schema comes from our stores table
        products = conn.execute("""
            SELECT p.title, lower(p.product_type), string_agg(DISTINCT v.color, ', ' ORDER BY v.color)
            FROM products p JOIN variants v USING (product_id)
            GROUP BY p.product_id, p.title, p.product_type ORDER BY 2, 1""").fetchall()
        codes = conn.execute("SELECT code, title FROM discounts ORDER BY discount_id").fetchall()
        locations = conn.execute("SELECT name, type FROM locations ORDER BY location_id").fetchall()
        first, last = conn.execute(
            "SELECT min((created_at AT TIME ZONE %(tz)s)::date), max((created_at AT TIME ZONE %(tz)s)::date) "
            "FROM orders", {"tz": store.timezone}).fetchone()
    lines = [f"Data covers {first} to {last}. Treat {last} as today when the question uses relative dates "
             f"('last month', 'last 3 months', 'this year'), and say so in your assumptions.", "",
             "## Product catalogue (title | type | colours)"]
    lines += [f"- {t} | {ty} | {c}" for t, ty, c in products]
    lines += ["", "## Locations (name | type)"] + [f"- {n} | {t}" for n, t in locations]
    lines += ["", "## Discount codes and sales"] + [f"- {c}: {t}" for c, t in codes]
    return "\n".join(lines), str(last)


def schema_text(store: Store = DEMO) -> str:
    """The schema description with this store's name, currency, time zone and tax filled in."""
    return SCHEMA_DESCRIPTION.read_text().format(
        store_name=store.name, currency=store.currency, timezone=store.timezone, tax_name=store.tax_name,
        tax_divisor=store.tax_divisor)

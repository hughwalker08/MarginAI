"""Build the store-specific part of the prompt: what this particular store sells.

The schema description says how the data is shaped; this says what is in it, so the model can
map loose wording ("the blue shirt dress") onto real products, colours and codes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psycopg

from ..stores import DEMO, Store

SCHEMA_DESCRIPTION = Path(__file__).parents[2] / "db" / "schema_description.md"


FULL_MAX = int(os.environ.get("CATALOGUE_FULL_MAX", 150))  # list every product up to this many; search above it
MAX_CODES = 40


@dataclass
class StoreContext:
    text: str
    as_of: str  # the date the model should treat as "today"
    search_mode: bool  # True: the catalogue is searched per question instead of listed in full


def build_store_context(database_url: str, store: Store = DEMO) -> StoreContext:
    with psycopg.connect(database_url) as conn:
        conn.execute(f'SET search_path TO "{store.schema}"')  # schema comes from our stores table
        n_products = conn.execute("SELECT count(*) FROM products").fetchone()[0]
        search_mode = n_products > FULL_MAX
        locations = conn.execute("SELECT name, type FROM locations ORDER BY location_id").fetchall()
        codes = conn.execute(
            "SELECT d.code, d.title FROM discounts d LEFT JOIN orders o USING (discount_id) "
            "GROUP BY d.discount_id, d.code, d.title ORDER BY count(o.order_id) DESC, d.discount_id LIMIT %s",
            (MAX_CODES,)).fetchall()
        first, last, today = conn.execute(
            "SELECT min((created_at AT TIME ZONE %(tz)s)::date), max((created_at AT TIME ZONE %(tz)s)::date), "
            "(now() AT TIME ZONE %(tz)s)::date FROM orders", {"tz": store.timezone}).fetchone()
        if search_mode:
            types = conn.execute(
                "SELECT coalesce(lower(product_type), 'other'), count(*) FROM products GROUP BY 1 ORDER BY 2 DESC LIMIT 30"
            ).fetchall()
            sellers = conn.execute(
                "SELECT p.title, sum(l.quantity) FROM order_lines l JOIN orders o USING (order_id) "
                "JOIN variants v USING (variant_id) JOIN products p USING (product_id) "
                "WHERE o.financial_status <> 'voided' GROUP BY p.title ORDER BY 2 DESC LIMIT 15").fetchall()
            catalogue = [
                "## Product catalogue",
                f"This store has {n_products:,} products, too many to list. Product types (count): "
                + ", ".join(f"{t} ({c})" for t, c in types) + ".",
                "Best sellers by units: " + "; ".join(f"{t} ({int(u):,})" for t, u in sellers) + ".",
                "Catalogue entries that may match each question are attached to it. If none fit, look the product up "
                "with ILIKE on products.title / product_type / variants.color instead of guessing a name."]
        else:
            products = conn.execute("""
                SELECT p.title, lower(p.product_type), string_agg(DISTINCT v.color, ', ' ORDER BY v.color)
                FROM products p JOIN variants v USING (product_id)
                GROUP BY p.product_id, p.title, p.product_type ORDER BY 2, 1""").fetchall()
            catalogue = ["## Product catalogue (title | type | colours)"] + [f"- {t} | {ty} | {c}" for t, ty, c in products]
    as_of = today if store.live else last
    head = (f"Today is {as_of} (the store's local date). Data covers {first} to {as_of}. Use {as_of} for relative dates "
            f"('last month', 'last 3 months', 'this year'), and say so in your assumptions."
            if store.live else
            f"Data covers {first} to {last}. Treat {last} as today when the question uses relative dates "
            f"('last month', 'last 3 months', 'this year'), and say so in your assumptions.")
    lines = [head, ""] + catalogue
    lines += ["", "## Locations (name | type)"] + [f"- {n} | {t}" for n, t in locations]
    lines += ["", "## Discount codes and sales" + (f" (the {MAX_CODES} most used)" if len(codes) == MAX_CODES else "")]
    lines += [f"- {c}: {t}" for c, t in codes]
    return StoreContext("\n".join(lines), str(as_of), search_mode)


def schema_text(store: Store = DEMO) -> str:
    """The schema description with this store's name, currency, time zone and tax filled in."""
    return SCHEMA_DESCRIPTION.read_text().format(
        store_name=store.name, currency=store.currency, timezone=store.timezone, tax_name=store.tax_name,
        tax_divisor=store.tax_divisor)

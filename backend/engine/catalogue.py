"""Catalogue search for stores with too many products to list in every prompt.

For a big catalogue the system prompt carries only a summary (types, counts, best sellers). Each question gets
its own short list of products that look relevant, found with a plain database search, so there is no extra
model call and no added latency worth measuring. Wording like "blue" also looks for its colour family.
"""
from __future__ import annotations

import re

import psycopg

from ..stores import Store

STOPWORDS = set("""a an the and or of for to in on at by with from is are was were be been do did does have has had
how what which who when where why many much more most least best top worst our my your we us me i you it its this
that these those there than then them their they as per each every all any some no not can could would should
show tell give list get last next first previous year month week day today yesterday sales sale sold selling
revenue profit margin total average count number orders order units unit products product items item customers
customer refund refunds discount discounts online store stores instore compare versus between over under about
into also just only please""".split())

# Words a shopper uses for a colour family, mapped to colour names stores actually use.
COLOUR_FAMILIES = {
    "blue": ["navy", "cobalt", "denim", "indigo", "sky", "royal", "teal"],
    "green": ["sage", "olive", "khaki", "forest", "moss", "emerald", "mint"],
    "red": ["rust", "burgundy", "cherry", "wine", "crimson", "maroon"],
    "pink": ["blush", "rose", "dusty pink", "coral"],
    "brown": ["camel", "tan", "chocolate", "mocha", "terracotta", "sand", "beige"],
    "white": ["ivory", "cream", "off white", "ecru"],
    "black": ["charcoal", "onyx"],
    "grey": ["gray", "charcoal", "slate", "stone"],
    "yellow": ["mustard", "ochre", "lemon", "gold"],
    "purple": ["violet", "plum", "lilac", "lavender"],
}


def _singular(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def search_terms(question: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) >= 3 and w not in STOPWORDS]
    terms: list[str] = []
    for w in words:
        w = _singular(w)
        for t in [w, *COLOUR_FAMILIES.get(w, [])]:
            if t not in terms:
                terms.append(t)
    return terms[:24]


def find_products(conn: psycopg.Connection, question: str, k: int = 25) -> list[tuple[str, str, str]]:
    """Up to k (title, type, colours) rows ranked by how many distinct search terms they match."""
    terms = search_terms(question)
    if not terms:
        return []
    pats = [f"%{t}%" for t in terms]
    rows = conn.execute("""
        SELECT p.title, coalesce(lower(p.product_type), ''), coalesce(string_agg(DISTINCT v.color, ', ' ORDER BY v.color), '')
        FROM products p LEFT JOIN variants v USING (product_id)
        GROUP BY p.product_id, p.title, p.product_type
        HAVING p.title ILIKE ANY(%(p)s) OR p.product_type ILIKE ANY(%(p)s) OR bool_or(v.color ILIKE ANY(%(p)s))
        LIMIT 400""", {"p": pats}).fetchall()

    def score(r) -> tuple[int, int]:
        title, ptype, colours = (r[0] or "").lower(), r[1].lower(), r[2].lower()
        hits = sum(1 for t in terms if t in title or t in ptype or t in colours)
        return (hits, sum(1 for t in terms if t in title))  # title matches break ties

    return sorted(rows, key=score, reverse=True)[:k]


def hint(database_url: str, store: Store, question: str, k: int = 25) -> str:
    """Text appended to a question: the catalogue entries that may be what the user is talking about."""
    with psycopg.connect(database_url) as conn:
        conn.execute(f'SET search_path TO "{store.schema}"')
        rows = find_products(conn, question, k)
    if not rows:
        return ""
    lines = [f"- {t} | {ty} | {c}" for t, ty, c in rows]
    return "[Catalogue entries that may match this question (title | type | colours)]\n" + "\n".join(lines)

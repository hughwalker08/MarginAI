"""Multi-turn eval scenarios: earlier turns are run for real, then the LAST turn (a follow-up that only
makes sense with the conversation so far) is graded against ground truth like the single-turn evals."""
from __future__ import annotations

from dataclasses import dataclass

from .questions import LOCAL, NET, NV, Q


@dataclass
class Scenario:
    id: str
    turns: list[str]  # the last one is graded
    final: Q
    keyword: str = ""  # for mode "meta": the clarification must mention this


def sc(id, turns, category, truth=None, mode="cells", keyword="", **kw) -> Scenario:
    truth = [truth] if isinstance(truth, str) else (truth or [])
    return Scenario(id, turns, Q(id, "followup", category, turns[-1], truth, mode=mode, **kw), keyword)


TOP_PRODUCT_BY_UNITS = (
    f"SELECT p.product_id FROM order_lines l JOIN orders o USING (order_id) JOIN variants v USING (variant_id) "
    f"JOIN products p USING (product_id) WHERE {NV} GROUP BY p.product_id ORDER BY sum(l.quantity) DESC LIMIT 1")


def monthly(channel: str) -> str:
    return (f"SELECT date_trunc('month', {LOCAL})::date, round(sum(o.total), 2) FROM orders o "
            f"WHERE {NV} AND o.sales_channel = '{channel}' GROUP BY 1")


SCENARIOS: list[Scenario] = [
    sc("f01", ["What was our revenue in each month?", "And just for online orders?"], "refine-filter",
       monthly("online"), mode="rows"),
    sc("f02", ["How much revenue did we make in December 2025?", "And in January 2026?"], "shift-period",
       f"SELECT round(sum(o.total), 2) FROM orders o WHERE {NV} AND {LOCAL}::date BETWEEN '2026-01-01' AND '2026-01-31'"),
    sc("f03", ["How many orders were placed online versus in store?", "What's the average order value for each of those?"],
       "same-groups",
       f"SELECT o.sales_channel, round(avg(o.total), 2) FROM orders o WHERE {NV} GROUP BY 1", mode="rows"),
    sc("f04", ["What are our top 5 products by units sold?", "How much revenue did the top one bring in?"], "pronoun",
       f"WITH t AS ({TOP_PRODUCT_BY_UNITS}) SELECT round(sum({NET}), 2) FROM order_lines l JOIN orders o USING (order_id) "
       f"JOIN variants v USING (variant_id) WHERE {NV} AND v.product_id IN (SELECT product_id FROM t)"),
    sc("f05", ["Which product type sells the most units?", "And which sells the least?"], "opposite",
       f"SELECT lower(p.product_type), sum(l.quantity) FROM order_lines l JOIN orders o USING (order_id) "
       f"JOIN variants v USING (variant_id) JOIN products p USING (product_id) WHERE {NV} GROUP BY 1 ORDER BY 2 ASC LIMIT 1"),
    sc("f06", ["Which state do most online orders ship to?", "What about the second most?"], "next-rank",
       f"SELECT o.shipping_state, count(*) FROM orders o WHERE {NV} AND o.sales_channel = 'online' "
       f"GROUP BY 1 ORDER BY 2 DESC OFFSET 1 LIMIT 1"),
    sc("f07", ["What are our top 3 products by revenue?", "Show me their gross profit too."], "add-metric",
       f"WITH top3 AS (SELECT p.product_id, p.title FROM order_lines l JOIN orders o USING (order_id) "
       f"JOIN variants v USING (variant_id) JOIN products p USING (product_id) WHERE {NV} GROUP BY 1, 2 "
       f"ORDER BY sum({NET}) DESC LIMIT 3) SELECT t.title, round(sum({NET} / 1.1 - v.cost * l.quantity), 2) "
       f"FROM order_lines l JOIN orders o USING (order_id) JOIN variants v USING (variant_id) "
       f"JOIN top3 t USING (product_id) WHERE {NV} AND v.cost IS NOT NULL GROUP BY t.title", mode="rows"),
    sc("f08", ["How much revenue did we make during the EOFY sale (19 June to 5 July 2026)?", "And how many orders was that?"],
       "carry-period",
       f"SELECT count(*) FROM orders o WHERE {NV} AND {LOCAL}::date BETWEEN '2026-06-19' AND '2026-07-05'"),
    sc("f09", ["How much have we refunded for each reason?", "Only show the ones above $10,000."], "filter-result",
       "SELECT reason, round(sum(amount), 2) FROM refunds GROUP BY 1 HAVING sum(amount) > 10000", mode="rows"),
    sc("f10", ["How many orders have been placed?", "How many products do we sell?"], "unrelated-new",
       "SELECT count(*) FROM products"),
    sc("f11", ["What was our revenue in each month?", "What was my last question?"], "meta", mode="meta",
       keyword="revenue"),
    sc("f12", ["Which colour sold the most units?", "I meant in winter, June to August 2026."], "correction",
       f"SELECT v.color, sum(l.quantity) FROM order_lines l JOIN orders o USING (order_id) "
       f"JOIN variants v USING (variant_id) WHERE {NV} AND {LOCAL}::date BETWEEN '2026-06-01' AND '2026-08-31' "
       f"GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
    sc("f13", ["How have sales of the cotton blue dress shirt changed over the last 3 months?",
               "Use the Linen Shirt then, all colours."], "resolve-ambiguity",
       [f"SELECT round(sum({NET}), 2) FROM order_lines l JOIN orders o USING (order_id) JOIN variants v USING (variant_id) "
        f"JOIN products p USING (product_id) WHERE {NV} AND p.title = 'Linen Shirt' "
        f"AND {LOCAL}::date BETWEEN '2026-07-01' AND '2026-09-30' GROUP BY date_trunc('month', {LOCAL})",
        f"SELECT sum(l.quantity) FROM order_lines l JOIN orders o USING (order_id) JOIN variants v USING (variant_id) "
        f"JOIN products p USING (product_id) WHERE {NV} AND p.title = 'Linen Shirt' "
        f"AND {LOCAL}::date BETWEEN '2026-07-01' AND '2026-09-30' GROUP BY date_trunc('month', {LOCAL})"],
       extra_rows_ok=True),
    sc("f14", ["How many orders were placed online?", "And in store?", "What's the total of both?"], "three-turn-chain",
       f"SELECT count(*) FROM orders o WHERE {NV}"),
    sc("f15", ["What was our revenue in each month?", "Just online orders.", "And in store instead?"], "swap-filter",
       monthly("pos"), mode="rows"),
    sc("f16", ["What are our top 5 products by units sold?", "How many orders have been placed?",
               "How many products do we sell?", "How many refunds have been issued?",
               "How many different colours do we stock?", "How many orders were voided?",
               "How many units of the top-selling product from my first question were refunded?"],
       "remember-six-back",
       f"WITH t AS ({TOP_PRODUCT_BY_UNITS}) SELECT sum(rl.quantity) FROM refund_lines rl "
       f"JOIN order_lines l USING (order_line_id) JOIN variants v USING (variant_id) "
       f"WHERE v.product_id IN (SELECT product_id FROM t)"),
]

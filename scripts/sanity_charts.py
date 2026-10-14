"""Render sanity-check charts from the loaded database to data_gen/output/sanity.png."""
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()
conn = psycopg.connect(os.environ.get("DATABASE_URL", "postgresql:///marginai"))
LOCAL = "created_at AT TIME ZONE 'Australia/Sydney'"
REAL = "financial_status <> 'voided'"


def q(sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, conn)


daily = q(f"SELECT ({LOCAL})::date AS d, sum(total) AS revenue FROM orders WHERE {REAL} GROUP BY 1 ORDER BY 1")
dow_hour = q(f"""SELECT extract(isodow FROM {LOCAL}) AS dow, extract(hour FROM {LOCAL}) AS hr, count(*) AS n
                 FROM orders GROUP BY 1, 2""")
by_type = q(f"""SELECT date_trunc('month', {LOCAL.replace('created_at', 'o.created_at')})::date AS m,
                lower(p.product_type) AS type, sum(l.unit_price * l.quantity - l.line_discount) AS revenue
                FROM order_lines l JOIN orders o USING (order_id) JOIN variants v USING (variant_id)
                JOIN products p USING (product_id) WHERE o.{REAL} GROUP BY 1, 2""")
top = q(f"""SELECT p.title, sum(l.quantity) AS units FROM order_lines l JOIN orders o USING (order_id)
            JOIN variants v USING (variant_id) JOIN products p USING (product_id)
            WHERE o.{REAL} GROUP BY 1 ORDER BY 2 DESC LIMIT 12""")
disc = q(f"""SELECT date_trunc('month', {LOCAL})::date AS m,
             sum(discount_total) / sum(subtotal) * 100 AS pct FROM orders WHERE {REAL} GROUP BY 1 ORDER BY 1""")
refund = q("""SELECT date_trunc('month', o.created_at)::date AS m,
              100.0 * count(DISTINCT r.order_id) / count(DISTINCT o.order_id) AS pct
              FROM orders o LEFT JOIN refunds r USING (order_id) GROUP BY 1 ORDER BY 1""")

fig, ax = plt.subplots(2, 3, figsize=(18, 9))
ax[0, 0].plot(daily.d, daily.revenue, lw=0.8); ax[0, 0].set_title("Daily revenue (AUD)")
pivot = dow_hour.pivot(index="dow", columns="hr", values="n").fillna(0)
ax[0, 1].imshow(pivot, aspect="auto", cmap="viridis"); ax[0, 1].set_title("Orders by weekday (Mon=top) x hour")
ax[0, 1].set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
pv = by_type.pivot(index="m", columns="type", values="revenue").fillna(0)
pv.plot.area(ax=ax[0, 2], legend=True, title="Monthly revenue by product type (seasonality)")
ax[1, 0].barh(top.title[::-1], top.units[::-1]); ax[1, 0].set_title("Top 12 products by units (bestsellers + long tail)")
ax[1, 1].bar(disc.m.astype(str), disc.pct); ax[1, 1].set_title("Discount as % of subtotal, by month")
ax[1, 1].tick_params(axis="x", rotation=60)
ax[1, 2].bar(refund.m.astype(str), refund.pct); ax[1, 2].set_title("% of orders with a refund, by month")
ax[1, 2].tick_params(axis="x", rotation=60)
plt.tight_layout()
out = Path(__file__).parents[1] / "data_gen" / "output" / "sanity.png"
plt.savefig(out, dpi=80)
print("Wrote", out)

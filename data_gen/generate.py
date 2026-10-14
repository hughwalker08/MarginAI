"""Seeded synthetic data for "Willow & Finch", a fictional Sydney clothing boutique.

Produces Shopify-shaped CSVs (one per table in db/migrations/001_schema.sql) covering
2025-10-01 .. 2026-09-30. Same seed -> identical output.

Usage: python -m data_gen.generate [--seed 42] [--out data_gen/output]
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ = ZoneInfo("Australia/Sydney")
START = date(2025, 10, 1)
END = date(2026, 9, 30)
PRICE_RISE_DATE = date(2026, 3, 1)

# --- Catalogue ---------------------------------------------------------------------

CLOTHING_SIZES = ["XS", "S", "M", "L", "XL"]
SIZE_WEIGHTS = [0.10, 0.28, 0.30, 0.22, 0.10]
PALETTE = ["Black", "White", "Ivory", "Navy", "Sage", "Terracotta", "Dusty Pink", "Camel",
           "Charcoal", "Cobalt", "Olive", "Rust", "Sand", "Stripe", "Floral"]

# type -> (names, price range, sizes, monthly seasonality Jan..Dec)
CATALOG: dict[str, tuple[list[str], tuple[int, int], list[str], list[float]]] = {
    "Dress": (
        ["Linen Wrap Dress", "Floral Midi Dress", "Satin Slip Dress", "Smocked Sundress",
         "Knit Midi Dress", "Shirt Dress", "Maxi Dress", "Pleated Dress"],
        (89, 189), CLOTHING_SIZES, [1.2, 1.0, .8, .7, .6, .5, .5, .6, .9, 1.2, 1.4, 1.6]),
    "Top": (
        ["Cotton Tee", "Linen Shirt", "Ribbed Tank", "Silk Camisole", "Oversized Poplin Shirt",
         "Puff Sleeve Blouse"],
        (39, 119), CLOTHING_SIZES, [1.2, 1.1, 1, .9, .8, .7, .7, .8, 1, 1.1, 1.2, 1.3]),
    "Knitwear": (
        ["Merino Crew Jumper", "Cable Knit Cardigan", "Wool Blend Vest", "Chunky Turtleneck"],
        (89, 169), CLOTHING_SIZES, [.15, .15, .4, .9, 1.5, 1.9, 1.9, 1.4, .7, .3, .2, .15]),
    "Outerwear": (
        ["Wool Coat", "Trench Coat", "Puffer Jacket", "Denim Jacket", "Linen Blazer"],
        (139, 329), CLOTHING_SIZES, [.15, .15, .4, .9, 1.4, 2.0, 2.0, 1.4, .7, .3, .2, .2]),
    "Pants": (
        ["High-Rise Jeans", "Linen Pants", "Wide Leg Trousers", "Cargo Pants", "Straight Leg Jeans"],
        (99, 169), CLOTHING_SIZES, [.9, .9, 1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1, 1, .9]),
    "Skirt": (
        ["Denim Mini Skirt", "Satin Midi Skirt", "Pleated Skirt", "Linen Wrap Skirt"],
        (69, 139), CLOTHING_SIZES, [1.2, 1.1, 1, .8, .7, .5, .5, .6, .9, 1.1, 1.2, 1.3]),
    "Swimwear": (
        ["One-Piece Swimsuit", "Bikini Top", "Bikini Bottom", "Rash Vest"],
        (49, 129), CLOTHING_SIZES, [1.8, 1.6, .9, .3, .1, .05, .05, .1, .4, 1, 1.5, 2.0]),
    "Accessories": (
        ["Leather Belt", "Silk Scarf", "Canvas Tote", "Straw Hat", "Wool Beanie", "Sunglasses"],
        (25, 95), ["One Size"], [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1.1, 1.5]),
}

# --- Promotions --------------------------------------------------------------------


@dataclass(frozen=True)
class Discount:
    discount_id: int
    code: str
    title: str
    kind: str
    value: float | None
    is_automatic: bool
    starts_on: date
    ends_on: date | None
    volume_boost: float = 1.0  # multiplier on daily order volume while active


DISCOUNTS = [
    Discount(1, "BLACKFRIDAY", "Black Friday 25% off", "percentage", 25, True,
             date(2025, 11, 27), date(2025, 12, 1), 1.9),
    Discount(2, "BOXINGDAY", "Boxing Day Sale 30% off", "percentage", 30, True,
             date(2025, 12, 26), date(2026, 1, 11), 1.6),
    Discount(3, "MIDSEASON", "Mid-Season Sale 15% off", "percentage", 15, True,
             date(2026, 3, 20), date(2026, 3, 29), 1.25),
    Discount(4, "EOFY", "End of Financial Year 20% off", "percentage", 20, True,
             date(2026, 6, 19), date(2026, 7, 5), 1.5),
    Discount(5, "SPRINGREFRESH", "Spring Refresh 15% off", "percentage", 15, True,
             date(2026, 9, 4), date(2026, 9, 14), 1.3),
    Discount(6, "WELCOME10", "Welcome 10% off first order", "percentage", 10, False,
             date(2025, 10, 1), None),
    Discount(7, "VIP15", "VIP 15% off", "percentage", 15, False, date(2025, 10, 1), None),
    Discount(8, "SAVE20", "$20 off orders over $150", "fixed_amount", 20, False,
             date(2025, 10, 1), date(2026, 3, 31)),
    Discount(9, "FREESHIP", "Free shipping", "free_shipping", None, False,
             date(2025, 10, 1), None),
    Discount(10, "EXPIRED5", "Old $5 voucher", "fixed_amount", 5, False,
             date(2025, 1, 1), date(2025, 9, 30)),  # never used
]
SALES = [d for d in DISCOUNTS if d.is_automatic]
BY_CODE = {d.code: d for d in DISCOUNTS}

LOCATIONS = [(1, "Online Store", "online"), (2, "Surry Hills Boutique", "pos"),
             (3, "Newtown Boutique", "pos")]

# --- Customers ---------------------------------------------------------------------

FIRST = ["Olivia", "Charlotte", "Mia", "Isla", "Amelia", "Ava", "Grace", "Chloe", "Sophie", "Emily",
         "Zoe", "Ruby", "Matilda", "Harper", "Lucy", "Ella", "Hannah", "Sienna", "Georgia", "Evie",
         "Jack", "Oliver", "Noah", "Liam", "Lachlan", "Ben", "Sam", "Tom", "Max", "Jess", "Kate",
         "Maddie", "Priya", "Mei", "Aisha", "Nina", "Tara", "Holly", "Bridget", "Imogen"]
LAST = ["Smith", "Jones", "Williams", "Brown", "Wilson", "Taylor", "Nguyen", "Kim", "Patel", "Singh",
        "Lee", "Chen", "Wang", "Martin", "Anderson", "Thompson", "White", "Harris", "Clarke", "Walker",
        "Murphy", "Kelly", "Ryan", "O'Brien", "Campbell", "Stewart", "Morgan", "Reid", "Hughes",
        "Bennett", "Fraser", "Cooper", "Ward", "Hall", "Young", "King", "Wright", "Scott", "Green", "Baker"]
EMAIL_DOMAINS = ["gmail.com", "gmail.com", "gmail.com", "outlook.com", "hotmail.com", "icloud.com",
                 "yahoo.com.au", "bigpond.com"]
CITIES = [("Sydney", "NSW", .40), ("Newcastle", "NSW", .05), ("Wollongong", "NSW", .04),
          ("Byron Bay", "NSW", .02), ("Melbourne", "VIC", .15), ("Brisbane", "QLD", .10),
          ("Gold Coast", "QLD", .04), ("Perth", "WA", .05), ("Adelaide", "SA", .05),
          ("Canberra", "ACT", .05), ("Hobart", "TAS", .02), ("Darwin", "NT", .03)]

# --- Volume model ------------------------------------------------------------------

DOW_FACTOR = [0.85, 0.85, 0.90, 1.05, 1.15, 1.45, 1.10]  # Mon..Sun
MONTH_FACTOR = [1.0, 0.9, 0.95, 0.95, 1.05, 1.1, 1.0, 0.9, 0.95, 1.0, 1.1, 1.5]
BASE_ORDERS_PER_DAY = 36
ONLINE_SHARE = 0.62

ONLINE_HOUR_W = np.array([.4, .2, .1, .1, .1, .2, .5, 1, 1.5, 1.7, 1.8, 2, 2.4, 2.2, 1.9, 1.8,
                          2, 2.4, 3, 4.2, 4.8, 4.2, 2.6, 1.2])
POS_HOUR_W = np.zeros(24)
POS_HOUR_W[10:18] = [1.0, 1.8, 2.8, 3.0, 2.6, 2.2, 1.6, 0.6]  # 10:00..17:59


def _round2(x: float) -> float:
    return round(float(x) + 1e-9, 2)


def _to_utc(d: date, hour: int, minute: int, second: int) -> datetime:
    local = datetime.combine(d, time(hour, minute, second), tzinfo=TZ)
    return local.astimezone(timezone.utc)


def _active_sale(d: date) -> Discount | None:
    for s in SALES:
        if s.starts_on <= d <= s.ends_on:
            return s
    return None


def _valid(code: str, d: date) -> bool:
    disc = BY_CODE[code]
    return disc.starts_on <= d and (disc.ends_on is None or d <= disc.ends_on)


# --- Builders ----------------------------------------------------------------------


def build_catalog(rng: np.random.Generator):
    products, variants = [], []
    prod_meta = []  # per product: type, season, popularity, old_price
    vid = 1
    names = [(t, n) for t, (ns, *_rest) in CATALOG.items() for n in ns]
    ranks = rng.permutation(len(names))
    for pid, ((ptype, title), rank) in enumerate(zip(names, ranks), start=1):
        _, (lo, hi), sizes, season = CATALOG[ptype]
        price = round(rng.uniform(lo, hi) / 5) * 5 - 0.05
        has_cost = rng.random() > 0.05
        cost = _round2(price / 1.1 * rng.uniform(0.28, 0.50)) if has_cost else None
        colors = list(rng.choice(PALETTE, size=int(rng.integers(2, 5)), replace=False))
        old_price = price - 10 if rng.random() < 0.12 else None  # raised on PRICE_RISE_DATE
        shown_type = ptype.lower() if rng.random() < 0.07 else ptype  # deliberate casing mess
        created = _to_utc(START - timedelta(days=int(rng.integers(30, 500))), 9, 0, 0)
        products.append((pid, title, shown_type, "Willow & Finch", "active", created))
        vlist = []
        cw = rng.dirichlet(np.ones(len(colors)) * 2)
        for ci, color in enumerate(colors):
            for si, size in enumerate(sizes):
                sw = SIZE_WEIGHTS[si] if size != "One Size" else 1.0
                variants.append((vid, pid, f"WF-{pid:03d}-{color[:3].upper()}-{size.replace(' ', '')}",
                                 size, color, price, cost))
                vlist.append((vid, sw * cw[ci]))
                vid += 1
        ids = np.array([v for v, _ in vlist])
        w = np.array([w for _, w in vlist])
        prod_meta.append(dict(pid=pid, type=ptype, season=season, pop=1.0 / (rank + 1) ** 0.85,
                              price=price, old_price=old_price, vids=ids, vw=w / w.sum()))
    return products, variants, prod_meta


def build_customers(rng: np.random.Generator, n: int = 3600):
    rows = []
    city_p = np.array([c[2] for c in CITIES]); city_p = city_p / city_p.sum()
    span = (END - date(2023, 6, 1)).days
    for cid in range(1, n + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        email = None
        if rng.random() > 0.06:
            email = f"{first}.{last}{int(rng.integers(1, 99)) if rng.random() < .4 else ''}@" \
                    f"{rng.choice(EMAIL_DOMAINS)}".lower().replace("'", "")
        city, state = (None, None)
        if rng.random() > 0.03:
            c = CITIES[int(rng.choice(len(CITIES), p=city_p))]
            city, state = c[0], c[1]
        created_day = date(2023, 6, 1) + timedelta(days=int(span * rng.beta(1.4, 1.0)))
        rows.append(dict(customer_id=cid, first_name=str(first), last_name=str(last), email=email,
                         city=city, state=state, accepts_marketing=bool(rng.random() < 0.55),
                         created_at=_to_utc(created_day, int(rng.integers(8, 22)), int(rng.integers(60)), 0)))
    rows.sort(key=lambda r: r["created_at"])
    for i, r in enumerate(rows, start=1):  # ids ascend with signup time
        r["customer_id"] = i
    return rows


def generate(seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    products, variants, meta = build_catalog(rng)
    customers = build_customers(rng)
    n_cust = len(customers)
    created_days = [(c["created_at"].astimezone(TZ).date() - START).days for c in customers]
    activity = rng.lognormal(0, 0.9, n_cust)
    cum_activity = np.cumsum(activity)
    vip = set(rng.choice(np.arange(1, n_cust + 1), size=int(n_cust * 0.06), replace=False).tolist())
    cust_state = {c["customer_id"]: c["state"] for c in customers}
    seen: set[int] = set()

    n_days = (END - START).days + 1
    orders, lines = [], []
    order_id = line_id = 0
    prices_by_vid = {v[0]: v[5] for v in variants}
    pid_by_vid = {v[0]: v[1] for v in variants}
    meta_by_pid = {m["pid"]: m for m in meta}
    pop = np.array([m["pop"] for m in meta])

    for di in range(n_days):
        day = START + timedelta(days=di)
        sale = _active_sale(day)
        growth = 1.0 + 0.25 * di / n_days
        mean = (BASE_ORDERS_PER_DAY * growth * DOW_FACTOR[day.weekday()] * MONTH_FACTOR[day.month - 1]
                * (sale.volume_boost if sale else 1.0))
        n_orders = int(rng.poisson(mean))
        season_w = np.array([m["season"][day.month - 1] for m in meta])
        prod_p = pop * season_w
        prod_p = prod_p / prod_p.sum()

        day_orders = []
        for _ in range(n_orders):
            online = rng.random() < ONLINE_SHARE
            if online:
                loc = 1
                hw = ONLINE_HOUR_W
            else:
                loc = 2 if rng.random() < 0.6 else 3
                hw = POS_HOUR_W.copy()
                if day.weekday() == 6:
                    hw[17] = 0
            hour = int(rng.choice(24, p=hw / hw.sum()))
            ts = _to_utc(day, hour, int(rng.integers(60)), int(rng.integers(60)))
            day_orders.append((ts, online, loc))
        day_orders.sort(key=lambda o: o[0])

        for ts, online, loc in day_orders:
            order_id += 1
            # customer
            cid = None
            guest_p = 0.08 if online else 0.45
            k = bisect_right(created_days, di)
            if rng.random() > guest_p and k > 0:
                cid = int(np.searchsorted(cum_activity[:k], rng.random() * cum_activity[k - 1],
                                          side="right")) + 1
                cid = min(cid, k)
            first_in_data = cid is not None and cid not in seen
            if cid is not None:
                seen.add(cid)

            # basket
            n_lines = int(rng.choice([1, 2, 3, 4], p=[.55, .28, .12, .05]))
            pidx = rng.choice(len(meta), size=n_lines, replace=False, p=prod_p)
            order_lines = []
            for pi in pidx:
                m = meta[int(pi)]
                vid = int(rng.choice(m["vids"], p=m["vw"]))
                qty = int(rng.choice([1, 2, 3], p=[.88, .10, .02]))
                price = m["price"]
                if m["old_price"] is not None and day < PRICE_RISE_DATE:
                    price = m["old_price"]
                order_lines.append(dict(variant_id=vid, quantity=qty, unit_price=_round2(price),
                                        line_discount=0.0))
            subtotal = _round2(sum(l["unit_price"] * l["quantity"] for l in order_lines))

            # discount
            disc = None
            shipping = 0.0 if not online else 9.95
            if sale and rng.random() < 0.9:
                touched = False
                for l in order_lines:
                    if rng.random() < 0.85:
                        l["line_discount"] = _round2(l["unit_price"] * l["quantity"] * sale.value / 100)
                        touched = True
                if touched:
                    disc = sale
            elif online:
                if first_in_data and rng.random() < 0.55 and _valid("WELCOME10", day):
                    disc = BY_CODE["WELCOME10"]
                elif cid in vip and rng.random() < 0.5:
                    disc = BY_CODE["VIP15"]
                elif subtotal >= 150 and _valid("SAVE20", day) and rng.random() < 0.18:
                    disc = BY_CODE["SAVE20"]
                elif rng.random() < 0.04:
                    disc = BY_CODE["FREESHIP"]
            elif cid in vip and rng.random() < 0.3:
                disc = BY_CODE["VIP15"]
            if disc is not None and not disc.is_automatic:
                if disc.kind == "percentage":
                    for l in order_lines:
                        l["line_discount"] = _round2(l["unit_price"] * l["quantity"] * disc.value / 100)
                elif disc.kind == "fixed_amount":
                    left = disc.value
                    for i, l in enumerate(order_lines):
                        share = left if i == len(order_lines) - 1 else _round2(disc.value * l["unit_price"]
                                                                              * l["quantity"] / subtotal)
                        l["line_discount"] = share
                        left = _round2(left - share)
                elif disc.kind == "free_shipping":
                    shipping = 0.0
            discount_total = _round2(sum(l["line_discount"] for l in order_lines))
            if online and shipping and subtotal - discount_total >= 150:
                shipping = 0.0
            total = _round2(subtotal - discount_total + shipping)
            voided = online and rng.random() < 0.012
            ship_state = (cust_state.get(cid) if cid else None) if online else "NSW"
            if online and ship_state is None:
                ship_state = str(rng.choice([c[1] for c in CITIES]))
            orders.append(dict(
                order_id=order_id, order_number=1000 + order_id, customer_id=cid, location_id=loc,
                sales_channel="online" if online else "pos",
                discount_id=disc.discount_id if disc else None, created_at=ts,
                financial_status="voided" if voided else "paid", subtotal=subtotal,
                discount_total=discount_total, shipping_total=shipping, tax_total=_round2(total / 11),
                total=total, shipping_state=ship_state))
            for l in order_lines:
                line_id += 1
                lines.append(dict(order_line_id=line_id, order_id=order_id, **l))

    orders_df = pd.DataFrame(orders)
    lines_df = pd.DataFrame(lines)

    # --- refunds ---
    refunds, refund_lines = [], []
    reasons = ["Wrong size", "Changed mind", "Faulty or damaged", "Not as described", "Arrived late"]
    reason_p = [.38, .27, .15, .13, .07]
    lines_by_order = {oid: g for oid, g in lines_df.groupby("order_id")}
    end_ts = _to_utc(END, 23, 59, 59)
    rid = rlid = 0
    refund_total_by_order: dict[int, float] = {}
    for o in orders:
        if o["financial_status"] == "voided":
            continue
        if rng.random() >= (0.09 if o["sales_channel"] == "online" else 0.025):
            continue
        created = o["created_at"] + timedelta(days=float(rng.uniform(2, 35)))
        if created > end_ts:
            continue
        g = lines_by_order[o["order_id"]]
        take = g if rng.random() < 0.2 else g.sample(n=1, random_state=int(rng.integers(1 << 31)))
        rid += 1
        total_refund = 0.0
        for _, l in take.iterrows():
            rq = int(rng.integers(1, l["quantity"] + 1))
            amt = _round2((l["unit_price"] * l["quantity"] - l["line_discount"]) * rq / l["quantity"])
            rlid += 1
            refund_lines.append(dict(refund_line_id=rlid, refund_id=rid,
                                     order_line_id=int(l["order_line_id"]), quantity=rq, amount=amt))
            total_refund += amt
        refunds.append(dict(refund_id=rid, order_id=o["order_id"], created_at=created,
                            reason=str(rng.choice(reasons, p=reason_p)),
                            restocked=bool(rng.random() < 0.8), amount=_round2(total_refund)))
        refund_total_by_order[o["order_id"]] = total_refund
    for o in orders:
        r = refund_total_by_order.get(o["order_id"])
        if r is not None:
            merch = o["total"] - o["shipping_total"]
            o["financial_status"] = "refunded" if r >= merch - 0.01 else "partially_refunded"
    orders_df = pd.DataFrame(orders)

    # --- duplicate customers (deliberate mess) ---
    next_cid = n_cust + 1
    dup_rows = []
    orders_by_cust = orders_df.groupby("customer_id").indices
    for i in rng.choice(n_cust, size=int(n_cust * 0.04), replace=False):
        orig = customers[int(i)]
        idxs = orders_by_cust.get(orig["customer_id"])
        if idxs is None or len(idxs) < 2:
            continue
        email = orig["email"]
        mode = rng.random()
        if email and mode < 0.4:
            email = email.upper() if rng.random() < 0.5 else email.replace("@", "+shop@")
        elif mode < 0.7:
            email = None
        dup = dict(orig, customer_id=next_cid, email=email,
                   created_at=orig["created_at"] + timedelta(days=int(rng.integers(5, 200))))
        moved = [int(x) for x in idxs if rng.random() < 0.5]
        if moved:
            orders_df.loc[moved, "customer_id"] = next_cid
        dup_rows.append(dup)
        next_cid += 1
    customers_df = pd.DataFrame(customers + dup_rows)
    orders_df["customer_id"] = orders_df["customer_id"].astype("Int64")
    orders_df["discount_id"] = orders_df["discount_id"].astype("Int64")

    disc_df = pd.DataFrame([dict(discount_id=d.discount_id, code=d.code, title=d.title, kind=d.kind,
                                 value=d.value, is_automatic=d.is_automatic, starts_on=d.starts_on,
                                 ends_on=d.ends_on) for d in DISCOUNTS])
    return {
        "locations": pd.DataFrame(LOCATIONS, columns=["location_id", "name", "type"]),
        "products": pd.DataFrame(products, columns=["product_id", "title", "product_type", "vendor",
                                                     "status", "created_at"]),
        "variants": pd.DataFrame(variants, columns=["variant_id", "product_id", "sku", "size", "color",
                                                     "price", "cost"]),
        "customers": customers_df,
        "discounts": disc_df,
        "orders": orders_df,
        "order_lines": lines_df,
        "refunds": pd.DataFrame(refunds),
        "refund_lines": pd.DataFrame(refund_lines),
    }


def write_csvs(tables: dict[str, pd.DataFrame], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "output")
    args = ap.parse_args()
    tables = generate(args.seed)
    write_csvs(tables, args.out)
    for name, df in tables.items():
        print(f"{name:14s} {len(df):>7,} rows")
    print(f"Wrote CSVs to {args.out}")


if __name__ == "__main__":
    main()

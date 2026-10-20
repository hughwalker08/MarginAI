"""Turn Shopify's bulk JSONL into rows for our store tables. Pure functions: no network, no database.

Bulk output is one JSON object per line; objects inside a connection arrive as their own lines carrying
`__parentId` (the GID of the object they belong to), parents before children.

Assumptions worth knowing (each is also true of the synthetic demo data):
- Amounts are in the shop's own currency (`shopMoney`), as decimals.
- Orders flagged `test`, and nothing else, are dropped. Cancelled orders become 'voided' so they never count as sales.
- 'pos' means Shopify POS (`sourceName == "pos"`); every other source is 'online'.
- No customer names or emails are read: a customer is only an id plus the date of their first order seen.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

ONLINE_LOCATION_ID = 0
UNKNOWN_POS_LOCATION_ID = -1
NO_VARIANT_ID = 0  # custom line items and deleted variants


def gid(value: str | None) -> int | None:
    """gid://shopify/Order/123?key=abc -> 123"""
    if not value:
        return None
    return int(value.split("?")[0].rsplit("/", 1)[-1])


def gid_type(value: str) -> str:
    return value.split("?")[0].rsplit("/", 2)[-2]


def money(node: dict | None) -> Decimal:
    try:
        return Decimal(node["shopMoney"]["amount"])  # type: ignore[index]
    except (TypeError, KeyError):
        return Decimal("0")


def ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _edges(conn) -> list[dict]:
    """A nested connection may arrive as {"edges": [{"node": ...}]}, {"nodes": [...]} or a plain list."""
    if not conn:
        return []
    if isinstance(conn, list):
        return conn
    if "nodes" in conn:  # the `nodes { ... }` shorthand
        return conn["nodes"]
    return [e.get("node", e) for e in conn.get("edges", [])]


def map_status(display: str | None, cancelled_at: str | None) -> str:
    if cancelled_at:
        return "voided"
    return {"PAID": "paid", "PARTIALLY_REFUNDED": "partially_refunded", "REFUNDED": "refunded",
            "VOIDED": "voided", "EXPIRED": "voided"}.get(display or "", "paid")  # pending/authorised still count as sales


# ---------------------------------------------------------------- products

@dataclass
class ProductBatch:
    products: list[dict] = field(default_factory=list)
    variants: list[dict] = field(default_factory=list)


def _option(options: list[dict], *names: str) -> str | None:
    for o in options or []:
        if (o.get("name") or "").strip().lower() in names:
            return o.get("value")
    return None


def _variant_row(node: dict, product_id: int | None) -> dict:
    options = node.get("selectedOptions") or []
    cost = (((node.get("inventoryItem") or {}).get("unitCost")) or {}).get("amount")
    return {"variant_id": gid(node["id"]), "product_id": product_id, "sku": node.get("sku") or "",
            "size": _option(options, "size"), "color": _option(options, "color", "colour"),
            "price": Decimal(node.get("price") or "0"), "cost": Decimal(cost) if cost is not None else None}


def parse_products(lines) -> ProductBatch:
    batch = ProductBatch()
    for obj in lines:
        t = gid_type(obj["id"])
        if t == "Product":
            batch.products.append({
                "product_id": gid(obj["id"]), "title": obj.get("title") or "", "product_type": obj.get("productType") or None,
                "vendor": obj.get("vendor") or None, "status": (obj.get("status") or "active").lower(),
                "created_at": ts(obj.get("createdAt"))})
            for v in _edges(obj.get("variants")):  # variants delivered inline instead of as child lines
                batch.variants.append(_variant_row(v, gid(obj["id"])))
        elif t == "ProductVariant":
            batch.variants.append(_variant_row(obj, gid(obj.get("__parentId"))))
    return batch


# ------------------------------------------------------------------ orders

@dataclass
class OrderBatch:
    orders: list[dict] = field(default_factory=list)
    order_lines: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)
    refund_lines: list[dict] = field(default_factory=list)
    discounts: dict[int, dict] = field(default_factory=dict)
    customers: dict[int, dict] = field(default_factory=dict)

    @property
    def order_ids(self) -> list[int]:
        return [o["order_id"] for o in self.orders]


def discount_id(key: str) -> int:
    """Stable id from the code or title (Shopify discount applications have no id of their own)."""
    return int(hashlib.md5(key.lower().encode()).hexdigest()[:15], 16)


def _discount(app: dict, created: datetime) -> dict | None:
    key = app.get("code") or app.get("title")
    if not key:
        return None
    value = app.get("value") or {}
    kind, amount = "fixed_amount", None
    if app.get("targetType") == "SHIPPING_LINE":
        kind = "free_shipping"
    elif value.get("__typename") == "PricingPercentageValue":
        kind, amount = "percentage", Decimal(str(value.get("percentage")))
    elif value.get("amount") is not None:
        amount = Decimal(value["amount"])
    return {"discount_id": discount_id(key), "code": key, "title": app.get("title") or key, "kind": kind,
            "value": amount, "is_automatic": app.get("__typename") != "DiscountCodeApplication",
            "starts_on": created.date(), "ends_on": None}


def parse_orders(lines) -> OrderBatch:
    orders: dict[str, dict] = {}
    discount_apps: dict[str, list[dict]] = {}
    line_items: dict[str, list[dict]] = {}
    refunds: dict[str, dict] = {}  # refund gid -> {"order": order gid, "node": ..., "lines": [...]}

    def add_refund(order_gid: str, r: dict) -> None:
        entry = refunds.setdefault(r["id"], {"order": order_gid, "node": r, "lines": []})
        entry["lines"] += _edges(r.get("refundLineItems"))

    for obj in lines:
        parent = obj.get("__parentId")
        oid = obj.get("id")
        t = gid_type(oid) if oid else None
        if t == "Order":
            orders[oid] = obj
            for r in obj.get("refunds") or []:
                add_refund(oid, r)
            line_items.setdefault(oid, []).extend(_edges(obj.get("lineItems")))
            discount_apps.setdefault(oid, []).extend(_edges(obj.get("discountApplications")))
        elif t == "LineItem":
            line_items.setdefault(parent, []).append(obj)
        elif t == "Refund":
            add_refund(parent, obj)
        elif t == "RefundLineItem":
            if parent in refunds:
                refunds[parent]["lines"].append(obj)
            else:  # flattened under the order: attach to its latest refund
                mine = [e for e in refunds.values() if e["order"] == parent]
                if mine:
                    mine[-1]["lines"].append(obj)
        elif oid is None and "allocationMethod" in obj:  # a discount application (no id of its own)
            discount_apps.setdefault(parent, []).append(obj)

    batch = OrderBatch()
    for o_gid, o in orders.items():
        if o.get("test"):
            continue
        order_id, created = gid(o_gid), ts(o["createdAt"])
        pos = (o.get("sourceName") or "").lower() == "pos"
        loc = gid((o.get("retailLocation") or {}).get("id")) or UNKNOWN_POS_LOCATION_ID if pos else ONLINE_LOCATION_ID
        cust = gid((o.get("customer") or {}).get("id"))
        disc_id = None
        for app in discount_apps.get(o_gid, []):
            row = _discount(app, created)
            if row:
                disc_id = disc_id or row["discount_id"]
                prev = batch.discounts.get(row["discount_id"])
                if prev is None or row["starts_on"] < prev["starts_on"]:
                    batch.discounts[row["discount_id"]] = row
        batch.orders.append({
            "order_id": order_id, "order_number": int(re.sub(r"\D", "", o.get("name") or "") or 0),
            "customer_id": cust, "location_id": loc, "sales_channel": "pos" if pos else "online",
            "discount_id": disc_id, "created_at": created,
            "financial_status": map_status(o.get("displayFinancialStatus"), o.get("cancelledAt")),
            "subtotal": money(o.get("subtotalPriceSet")), "discount_total": money(o.get("totalDiscountsSet")),
            "shipping_total": money(o.get("totalShippingPriceSet")), "tax_total": money(o.get("totalTaxSet")),
            "total": money(o.get("totalPriceSet")),
            "shipping_state": ((o.get("shippingAddress") or {}).get("provinceCode")) or None})
        if cust is not None:
            first = batch.customers.get(cust)
            if first is None or created < first["created_at"]:
                batch.customers[cust] = {"customer_id": cust, "created_at": created}
        for li in line_items.get(o_gid, []):
            batch.order_lines.append({
                "order_line_id": gid(li["id"]), "order_id": order_id,
                "variant_id": gid((li.get("variant") or {}).get("id")) or NO_VARIANT_ID,
                "quantity": int(li.get("quantity") or 0), "unit_price": money(li.get("originalUnitPriceSet")),
                "line_discount": money(li.get("totalDiscountSet"))})
    for r_gid, entry in refunds.items():
        r, order_gid = entry["node"], entry["order"]
        if order_gid not in orders or orders[order_gid].get("test"):
            continue
        lines_ = entry["lines"]
        batch.refunds.append({
            "refund_id": gid(r_gid), "order_id": gid(order_gid), "created_at": ts(r.get("createdAt")),
            "reason": (r.get("note") or None), "amount": money(r.get("totalRefundedSet")),
            "restocked": any((ln.get("restockType") or "NO_RESTOCK") != "NO_RESTOCK" for ln in lines_)})
        for ln in lines_:
            li_id = gid((ln.get("lineItem") or {}).get("id"))
            if li_id is None:
                continue
            batch.refund_lines.append({
                "refund_line_id": gid(ln["id"]), "refund_id": gid(r_gid), "order_line_id": li_id,
                "quantity": int(ln.get("quantity") or 0), "amount": money(ln.get("subtotalSet"))})
    batch.refund_lines = [x for x in batch.refund_lines if x["quantity"] > 0]
    return batch


def apply_refund_details(batch: OrderBatch, nodes: list[dict | None]) -> None:
    """Fill in refund_lines (and each refund's `restocked`) from the follow-up `nodes(ids:)` query."""
    known_lines = {ln["order_line_id"] for ln in batch.order_lines}
    by_refund = {r["refund_id"]: r for r in batch.refunds}
    for node in nodes:
        for refund in (node or {}).get("refunds") or []:
            rid = gid(refund["id"])
            row = by_refund.get(rid)
            if row is None:
                continue
            restocked = False
            for ln in _edges(refund.get("refundLineItems")):
                li_id = gid((ln.get("lineItem") or {}).get("id"))
                qty = int(ln.get("quantity") or 0)
                restocked = restocked or (ln.get("restockType") or "NO_RESTOCK") != "NO_RESTOCK"
                if li_id is None or qty <= 0 or li_id not in known_lines:
                    continue
                batch.refund_lines.append({"refund_line_id": gid(ln["id"]), "refund_id": rid, "order_line_id": li_id,
                                           "quantity": qty, "amount": money(ln.get("subtotalSet"))})
            row["restocked"] = restocked

import pytest

from data_gen.generate import END, START, generate


@pytest.fixture(scope="module")
def tables():
    return generate(seed=7)


def test_deterministic(tables):
    again = generate(seed=7)
    for name, df in tables.items():
        assert df.equals(again[name]), name


def test_different_seed_differs(tables):
    assert not generate(seed=8)["orders"].equals(tables["orders"])


def test_foreign_keys(tables):
    t = tables
    assert set(t["order_lines"].order_id) <= set(t["orders"].order_id)
    assert set(t["order_lines"].variant_id) <= set(t["variants"].variant_id)
    assert set(t["variants"].product_id) <= set(t["products"].product_id)
    assert set(t["orders"].customer_id.dropna()) <= set(t["customers"].customer_id)
    assert set(t["orders"].discount_id.dropna()) <= set(t["discounts"].discount_id)
    assert set(t["refunds"].order_id) <= set(t["orders"].order_id)
    assert set(t["refund_lines"].order_line_id) <= set(t["order_lines"].order_line_id)


def test_order_totals_reconcile(tables):
    o, l = tables["orders"].set_index("order_id"), tables["order_lines"]
    gross = (l.unit_price * l.quantity).groupby(l.order_id).sum()
    disc = l.line_discount.groupby(l.order_id).sum()
    assert (o.subtotal - gross).abs().max() < 0.011
    assert (o.discount_total - disc).abs().max() < 0.011
    assert (o.total - (o.subtotal - o.discount_total + o.shipping_total)).abs().max() < 0.011


def test_dates_in_range_and_mess_present(tables):
    o = tables["orders"]
    local = o.created_at.dt.tz_convert("Australia/Sydney").dt.date
    assert local.min() >= START and local.max() <= END
    assert o.customer_id.isna().any()  # guest orders
    assert tables["variants"].cost.isna().any()  # missing costs
    assert set(o.financial_status) == {"paid", "partially_refunded", "refunded", "voided"}

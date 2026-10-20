import pytest

from backend.engine.validator import ValidationError, validate_sql

OK = [
    "SELECT count(*) FROM orders",
    "select * from orders o join order_lines l using (order_id) limit 5;",
    "WITH m AS (SELECT date_trunc('month', created_at) AS m, sum(total) t FROM orders GROUP BY 1) "
    "SELECT * FROM m",
    "SELECT 1 UNION SELECT 2",
    "SELECT lower(product_type) FROM products WHERE title ILIKE '%shirt%'",
]
BAD = [
    "",
    "DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET total = 0",
    "INSERT INTO orders SELECT * FROM orders",
    "SELECT 1; DROP TABLE orders",
    "SELECT * FROM orders; SELECT * FROM products",
    "CREATE TABLE x (a int)",
    "TRUNCATE orders",
    "SELECT * INTO newtable FROM orders",
    "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "SELECT * FROM orders FOR UPDATE",
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM query_log",
    "SELECT * FROM schema_migrations",
    "SELECT * FROM public.orders",
    "SELECT set_config('role', 'postgres', false)",
    "SELECT current_setting('is_superuser')",
    "SET ROLE postgres",
    "COPY orders TO '/tmp/x'",
    "SELEC * FROM orders",
]


@pytest.mark.parametrize("sql", OK)
def test_allows_read_queries(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize("sql", BAD)
def test_rejects_unsafe_queries(sql):
    with pytest.raises(ValidationError):
        validate_sql(sql)


def test_strips_trailing_semicolon():
    assert validate_sql("SELECT 1 FROM orders;") == "SELECT 1 FROM orders"


from backend.engine.validator import semantic_warnings  # noqa: E402


def test_lint_flags_order_lines_without_orders():
    bad = "SELECT count(*) FROM (SELECT order_id FROM order_lines GROUP BY 1 HAVING sum(quantity) > 1) t"
    assert semantic_warnings(bad, "orders with more than one unit")
    ok = ("SELECT count(*) FROM (SELECT l.order_id FROM order_lines l JOIN orders o USING (order_id) "
          "WHERE o.financial_status <> 'voided' GROUP BY 1 HAVING sum(l.quantity) > 1) t")
    assert semantic_warnings(ok, "x") == []
    assert semantic_warnings("SELECT count(*) FROM orders", "x") == []
    assert semantic_warnings("WITH l AS (SELECT * FROM order_lines) SELECT * FROM l JOIN orders USING (order_id)", "x") == []


def test_lint_is_skipped_when_the_question_is_about_voided_orders():
    assert semantic_warnings("SELECT count(*) FROM order_lines", "how many units were in voided orders?") == []


def test_lint_catches_typos_in_status_literals():
    bad = "SELECT count(*) FROM orders WHERE financial_status <> 'voidged'"
    assert semantic_warnings(bad, "orders?") and "voided" in semantic_warnings(bad, "orders?")[0]
    assert semantic_warnings("SELECT count(*) FROM orders WHERE sales_channel IN ('online', 'store')", "x")
    assert semantic_warnings("SELECT count(*) FROM orders WHERE financial_status <> 'voided' AND sales_channel = 'pos'", "x") == []
    assert semantic_warnings("SELECT count(*) FROM orders WHERE order_number = 'x1'", "x") == []


def test_lint_catches_order_totals_summed_after_joining_lines():
    bad = ("SELECT l.name, count(DISTINCT o.order_id), sum(ol.quantity), round(sum(o.total), 2) FROM locations l "
           "JOIN orders o USING (location_id) JOIN order_lines ol USING (order_id) GROUP BY 1")
    w = semantic_warnings(bad, "orders units and revenue per location")
    assert w and "repeats each amount" in w[0]
    assert semantic_warnings("SELECT sum(o.subtotal) FROM orders o JOIN order_lines ol USING (order_id)", "x")
    assert semantic_warnings("SELECT avg(o.discount_total) FROM orders o, order_lines ol WHERE o.order_id = ol.order_id", "x")
    # fine: line-level money after the join, order-level money without it, or each in its own subquery
    assert semantic_warnings("SELECT sum(ol.unit_price * ol.quantity - ol.line_discount) FROM orders o JOIN order_lines ol USING (order_id)", "x") == []
    assert semantic_warnings("SELECT sum(total) FROM orders", "x") == []
    good = ("SELECT lo.name, a.revenue, b.units FROM locations lo "
            "JOIN (SELECT location_id, sum(total) AS revenue FROM orders GROUP BY 1) a USING (location_id) "
            "JOIN (SELECT o.location_id, sum(l.quantity) AS units FROM order_lines l JOIN orders o USING (order_id) GROUP BY 1) b USING (location_id)")
    assert semantic_warnings(good, "x") == []
    cte = ("WITH r AS (SELECT location_id, sum(total) AS rev FROM orders GROUP BY 1), "
           "u AS (SELECT o.location_id, sum(l.quantity) AS n FROM orders o JOIN order_lines l USING (order_id) GROUP BY 1) "
           "SELECT * FROM r JOIN u USING (location_id)")
    assert semantic_warnings(cte, "x") == []


def test_lint_catches_order_totals_summed_after_joining_refunds():
    bad = ("SELECT round(sum(r.amount) * 100.0 / sum(o.total), 2) FROM orders o LEFT JOIN refunds r ON o.order_id = r.order_id "
           "WHERE o.financial_status <> 'voided'")
    w = semantic_warnings(bad, "what is our refund percentage?")
    assert w and "refunds" in w[0]
    # refund amounts summed together with order lines also multiply
    assert semantic_warnings("SELECT sum(r.amount) FROM refunds r JOIN refund_lines rl USING (refund_id)", "x")
    good = ("SELECT round(100 * (SELECT sum(r.amount) FROM refunds r JOIN orders o USING (order_id) WHERE o.financial_status <> 'voided') "
            "/ (SELECT sum(total) FROM orders WHERE financial_status <> 'voided'), 2)")
    assert semantic_warnings(good, "x") == []
    assert semantic_warnings("SELECT sum(r.amount) FROM refunds r JOIN orders o USING (order_id) WHERE o.financial_status <> 'voided'", "x") == []
    assert semantic_warnings("SELECT sum(amount) FROM refunds", "x") == []

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

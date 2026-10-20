from backend.engine.charts import suggest_chart


def test_time_series_is_line():
    c = suggest_chart(["month", "revenue"], [["2026-01-01", 10.0], ["2026-02-01", 12.0]])
    assert c == {"type": "line", "x": "month", "y": ["revenue"]}


def test_categories_are_bar():
    assert suggest_chart(["title", "units"], [["A", 3], ["B", 2]])["type"] == "bar"


def test_single_value_has_no_chart():
    assert suggest_chart(["total"], [[5]]) is None
    assert suggest_chart(["a", "b"], [["x", 1]]) is None


def test_leading_null_does_not_hide_numeric_column():
    rows = [["2026-07-01", 12, None], ["2026-08-01", 21, 12], ["2026-09-01", 16, 21]]
    c = suggest_chart(["month", "units", "prev_units"], rows)
    assert c == {"type": "line", "x": "month", "y": ["units", "prev_units"]}


def test_no_chart_when_the_category_repeats_like_top_products_per_store():
    cols = ["location_name", "product_title", "units_sold", "line_revenue"]
    rows = [["Redfern", f"P{i}", 70 - i, 1000.0 - i] for i in range(5)] + [["Rosebery", f"Q{i}", 30 - i, 500.0 - i] for i in range(5)]
    assert suggest_chart(cols, rows) is None
    one_measure = [[r[0], r[1], r[2]] for r in rows]
    assert suggest_chart(cols[:3], one_measure) is None  # five products per store is too many series: table instead


def test_grouped_bars_remain_for_a_few_series():
    rows = [["Online", "Q1", 10], ["Online", "Q2", 12], ["In store", "Q1", 8], ["In store", "Q2", 9]]
    assert suggest_chart(["channel", "quarter", "orders"], rows) == {
        "type": "bar", "x": "channel", "y": ["orders"], "series": "quarter"}
    assert suggest_chart(["month", "channel", "revenue"], [["2026-01-01", "a", 1.0], ["2026-01-01", "b", 2.0], ["2026-02-01", "a", 3.0]])["type"] == "line"


def test_identifier_columns_are_never_charted_as_measures():
    cols = ["first_name", "customer_id", "order_count", "total_spend"]
    rows = [["Ann", 9894855770331, 1, 6725], ["Bo", 8674711863515, 5, 6085.3], ["Cy", 9859971121371, 2, 3300]]
    assert suggest_chart(cols, rows)["y"] == ["order_count", "total_spend"]
    assert suggest_chart(["customer_id", "n"], [[1, 5], [2, 6]]) is None  # nothing but an id and a count: no chart

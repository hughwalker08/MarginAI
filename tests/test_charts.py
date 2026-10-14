from backend.engine.charts import suggest_chart


def test_time_series_is_line():
    c = suggest_chart(["month", "revenue"], [["2026-01-01", 10.0], ["2026-02-01", 12.0]])
    assert c == {"type": "line", "x": "month", "y": ["revenue"]}


def test_categories_are_bar():
    assert suggest_chart(["title", "units"], [["A", 3], ["B", 2]])["type"] == "bar"


def test_single_value_has_no_chart():
    assert suggest_chart(["total"], [[5]]) is None
    assert suggest_chart(["a", "b"], [["x", 1]]) is None

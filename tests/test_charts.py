import pandas as pd

from core.charts import choose


def test_single_scalar_gets_no_chart():
    frame = pd.DataFrame({"total_revenue": [1284310.5]})
    assert choose(frame, hint="bar", max_categories=25) is None


def test_empty_result_gets_no_chart():
    assert choose(pd.DataFrame(), hint="bar", max_categories=25) is None


def test_category_and_measure_gets_a_bar():
    frame = pd.DataFrame({"region": ["N", "S", "E", "W"], "revenue": [10, 20, 30, 40]})
    spec = choose(frame, hint="bar", max_categories=25)
    assert spec is not None
    assert spec.kind == "bar"
    assert spec.x == "region"
    assert spec.y == "revenue"


def test_date_and_measure_gets_a_line():
    frame = pd.DataFrame(
        {
            "month": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
            "revenue": [1, 2, 3],
        }
    )
    spec = choose(frame, hint="bar", max_categories=25)
    assert spec is not None
    assert spec.kind == "line"
    assert spec.x == "month"


def test_too_many_categories_gets_no_chart():
    frame = pd.DataFrame({"customer": [f"C{i}" for i in range(60)], "spend": list(range(60))})
    assert choose(frame, hint="bar", max_categories=25) is None


def test_wide_result_gets_no_chart():
    frame = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6], "d": [7, 8]})
    assert choose(frame, hint="bar", max_categories=25) is None


def test_single_row_two_columns_still_charts():
    frame = pd.DataFrame({"region": ["West"], "revenue": [1842900.0]})
    spec = choose(frame, hint="bar", max_categories=25)
    assert spec is not None
    assert spec.kind == "bar"


def test_model_hint_cannot_force_a_chart_on_a_scalar():
    frame = pd.DataFrame({"total": [42]})
    assert choose(frame, hint="line", max_categories=25) is None


def test_no_numeric_column_gets_no_chart():
    frame = pd.DataFrame({"city": ["Pune", "Delhi"], "segment": ["New", "VIP"]})
    assert choose(frame, hint="bar", max_categories=25) is None

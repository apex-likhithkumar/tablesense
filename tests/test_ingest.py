import duckdb
import pandas as pd
import pytest

from core.ingest import coerce_date_columns, load_files, table_name_from


def test_table_name_sanitises_spaces_and_case():
    assert table_name_from("Sales Data 2026.csv") == "sales_data_2026"


def test_table_name_prefixes_leading_digit():
    assert table_name_from("2026 orders.csv") == "t_2026_orders"


def test_iso_date_strings_become_real_dates():
    frame = pd.DataFrame({"order_date": ["2026-05-17", "2025-08-08", "2025-12-31"]})
    result = coerce_date_columns(frame)
    assert pd.api.types.is_datetime64_any_dtype(result["order_date"])


def test_id_columns_are_left_as_text():
    frame = pd.DataFrame({"order_id": ["O00001", "O00002", "O00003"]})
    result = coerce_date_columns(frame)
    assert not pd.api.types.is_datetime64_any_dtype(result["order_id"])


def test_numeric_looking_text_is_left_alone():
    frame = pd.DataFrame({"pincode": ["500081", "600001", "110001"]})
    result = coerce_date_columns(frame)
    assert not pd.api.types.is_datetime64_any_dtype(result["pincode"])


def test_loaded_csv_dates_are_queryable_as_dates(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("order_id,order_date,amount\nO1,2026-01-15,10\nO2,2026-02-20,20\n")

    class Upload:
        def __init__(self, p):
            self.name = p.name
            self._handle = open(p, "rb")

        def __getattr__(self, item):
            return getattr(self._handle, item)

    con = duckdb.connect(":memory:")
    loaded, failed = load_files(con, [Upload(path)])
    assert failed == []

    dtype = con.execute("DESCRIBE orders").fetchall()
    order_date_type = next(r[1] for r in dtype if r[0] == "order_date")
    assert "TIMESTAMP" in order_date_type or "DATE" in order_date_type

    months = con.execute(
        "SELECT COUNT(DISTINCT DATE_TRUNC('month', order_date)) FROM orders"
    ).fetchone()[0]
    assert months == 2

import duckdb
import pandas as pd
import pytest

from core.profile import (
    JoinCandidate,
    find_join_candidates,
    names_look_related,
    profile_table,
    schema_context,
)


def test_names_look_related_exact_match():
    assert names_look_related("customer_id", "customer_id") is True


def test_names_look_related_ignores_id_suffix():
    assert names_look_related("customer_id", "customer") is True


def test_names_look_related_matches_qualified_name():
    assert names_look_related("cust_customer_id", "customer_id") is True


def test_names_look_related_rejects_unrelated():
    assert names_look_related("region", "quantity") is False


@pytest.fixture()
def con():
    connection = duckdb.connect(":memory:")
    orders = pd.DataFrame(
        {
            "order_id": ["O1", "O2", "O3", "O4"],
            "customer_id": ["C1", "C1", "C2", "C3"],
            "amount": [100.0, 250.5, 90.0, None],
        }
    )
    customers = pd.DataFrame(
        {"customer_id": ["C1", "C2", "C3"], "city": ["Hyderabad", "Chennai", "Pune"]}
    )
    connection.register("_o", orders)
    connection.register("_c", customers)
    connection.execute("CREATE TABLE orders AS SELECT * FROM _o")
    connection.execute("CREATE TABLE customers AS SELECT * FROM _c")
    return connection


def test_profile_table_reports_rows_and_columns(con):
    profile = profile_table(con, "orders", sample_size=3)
    assert profile.name == "orders"
    assert profile.rows == 4
    assert [c.name for c in profile.columns] == ["order_id", "customer_id", "amount"]


def test_profile_table_reports_null_percentage(con):
    profile = profile_table(con, "orders", sample_size=3)
    amount = next(c for c in profile.columns if c.name == "amount")
    assert amount.null_pct == pytest.approx(25.0)


def test_find_join_candidates_detects_shared_key(con):
    profiles = [profile_table(con, "orders", 3), profile_table(con, "customers", 3)]
    candidates = find_join_candidates(con, profiles, min_overlap=0.5, limit=8)
    assert JoinCandidate("orders", "customer_id", "customers", "customer_id", 1.0) in candidates


def test_find_join_candidates_ignores_unrelated_columns(con):
    profiles = [profile_table(con, "orders", 3), profile_table(con, "customers", 3)]
    candidates = find_join_candidates(con, profiles, min_overlap=0.5, limit=8)
    assert all(c.left_column != "amount" for c in candidates)


def test_schema_context_quotes_columns_and_lists_joins(con):
    profiles = [profile_table(con, "orders", 3), profile_table(con, "customers", 3)]
    candidates = find_join_candidates(con, profiles, min_overlap=0.5, limit=8)
    text = schema_context(profiles, candidates)
    assert '"customer_id"' in text
    assert "orders.customer_id = customers.customer_id" in text
    assert "4 rows" in text

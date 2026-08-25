from core.guard import validate

TABLES = {"orders", "customers"}
CAP = 5000


def test_plain_select_passes():
    result = validate("SELECT region FROM orders", TABLES, CAP)
    assert result.ok is True


def test_limit_is_injected_when_absent():
    result = validate("SELECT region FROM orders", TABLES, CAP)
    assert "LIMIT 5000" in result.sql.upper()


def test_existing_limit_is_left_alone():
    result = validate("SELECT region FROM orders LIMIT 10", TABLES, CAP)
    assert "LIMIT 10" in result.sql.upper()
    assert "5000" not in result.sql


def test_delete_is_rejected():
    result = validate("DELETE FROM orders", TABLES, CAP)
    assert result.ok is False
    assert "SELECT" in result.error


def test_drop_is_rejected():
    result = validate("DROP TABLE orders", TABLES, CAP)
    assert result.ok is False


def test_update_is_rejected():
    result = validate("UPDATE orders SET region = 'X'", TABLES, CAP)
    assert result.ok is False


def test_multiple_statements_are_rejected():
    result = validate("SELECT 1 FROM orders; DROP TABLE orders", TABLES, CAP)
    assert result.ok is False
    assert "one statement" in result.error


def test_unknown_table_is_rejected():
    result = validate("SELECT * FROM salaries", TABLES, CAP)
    assert result.ok is False
    assert "salaries" in result.error


def test_cte_name_is_not_treated_as_unknown_table():
    sql = "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent"
    result = validate(sql, TABLES, CAP)
    assert result.ok is True


def test_join_across_known_tables_passes():
    sql = "SELECT c.city FROM orders o JOIN customers c ON c.customer_id = o.customer_id"
    result = validate(sql, TABLES, CAP)
    assert result.ok is True


def test_empty_input_is_rejected():
    result = validate("   ", TABLES, CAP)
    assert result.ok is False


def test_unparseable_input_is_rejected():
    result = validate("SELECT FROM WHERE ((", TABLES, CAP)
    assert result.ok is False


def test_attach_is_rejected():
    result = validate("ATTACH 'evil.db' AS evil", TABLES, CAP)
    assert result.ok is False


def test_copy_to_file_is_rejected():
    result = validate("COPY orders TO 'out.csv'", TABLES, CAP)
    assert result.ok is False

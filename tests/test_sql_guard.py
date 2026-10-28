"""Unit tests for the read-only SQL boundary."""

import pytest

from services.sql_guard import validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM products",
        "SELECT category, COUNT(*) FROM products GROUP BY category",
        (
            "SELECT p.category, SUM(o.quantity * p.price) AS revenue "
            "FROM orders AS o JOIN products AS p "
            "ON o.product_id = p.product_id GROUP BY p.category"
        ),
    ],
)
def test_validate_sql_accepts_supported_analytics(sql: str) -> None:
    assert validate_sql(sql).startswith("SELECT")


@pytest.mark.parametrize(
    ("sql", "exception"),
    [
        ("", ValueError),
        ("DELETE FROM products", TypeError),
        ("SELECT * FROM secrets", ValueError),
        ("SELECT * FROM main.products", ValueError),
        ("SELECT * FROM products; SELECT * FROM orders", ValueError),
        ("WITH items AS (SELECT * FROM products) SELECT * FROM items", ValueError),
        ("SELECT RANDOM() FROM products", ValueError),
    ],
)
def test_validate_sql_rejects_unsafe_or_unsupported_queries(
    sql: str,
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        validate_sql(sql)

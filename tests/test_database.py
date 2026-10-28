"""Integration checks for the deterministic seeded DuckDB database."""

from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "business.duckdb"


def test_seeded_database_supports_category_profit_analysis() -> None:
    """Verify the demo database has plausible category aggregates."""
    if not DB_PATH.exists():
        pytest.skip("Run `uv run python scripts/seed_database.py` first")

    query = """
        SELECT
            p.category,
            ROUND(SUM(o.quantity * p.price), 2) AS revenue,
            ROUND(SUM(o.quantity * (p.price - p.unit_cost)), 2) AS gross_profit
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
        GROUP BY p.category
        ORDER BY revenue DESC
    """

    with duckdb.connect(str(DB_PATH), read_only=True) as connection:
        rows = connection.execute(query).fetchall()

    assert len(rows) == 3
    assert all(revenue >= gross_profit for _, revenue, gross_profit in rows)


def test_headphones_pricing_scenario_oracle() -> None:
    """Keep known scenario results available for live grounding evaluations."""
    if not DB_PATH.exists():
        pytest.skip("Run `uv run python scripts/seed_database.py` first")

    query = """
        SELECT
            SUM(o.quantity) AS baseline_units,
            ROUND(SUM(o.quantity * p.price), 2) AS baseline_revenue,
            ROUND(SUM(o.quantity * (p.price - p.unit_cost)), 2)
                AS baseline_gross_profit,
            ROUND(SUM(o.quantity) * (p.price * 1.05), 2) AS revenue_0,
            ROUND(SUM(o.quantity) * (p.price * 1.05 - p.unit_cost), 2)
                AS gross_profit_0,
            ROUND(SUM(o.quantity) * 0.95 * (p.price * 1.05), 2) AS revenue_5,
            ROUND(
                SUM(o.quantity) * 0.95 * (p.price * 1.05 - p.unit_cost),
                2
            ) AS gross_profit_5,
            ROUND(SUM(o.quantity) * 0.90 * (p.price * 1.05), 2) AS revenue_10,
            ROUND(
                SUM(o.quantity) * 0.90 * (p.price * 1.05 - p.unit_cost),
                2
            ) AS gross_profit_10
        FROM orders AS o
        JOIN products AS p ON o.product_id = p.product_id
        WHERE p.product_name = 'Headphones'
        GROUP BY p.price, p.unit_cost
    """

    with duckdb.connect(str(DB_PATH), read_only=True) as connection:
        result = connection.execute(query).fetchone()

    assert result == (
        40,
        6000.0,
        2800.0,
        6300.0,
        3100.0,
        5985.0,
        2945.0,
        5670.0,
        2790.0,
    )

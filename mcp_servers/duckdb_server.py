"""Expose safe, read-only business analytics over an MCP stdio server."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from mcp.server import MCPServer

from services.sql_guard import validate_sql

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "business.duckdb"

mcp = MCPServer("Business Analytics DuckDB")


def get_connection() -> duckdb.DuckDBPyConnection:
    """Open a read-only connection to the seeded business database."""
    return duckdb.connect(str(DB_PATH), read_only=True)


@mcp.tool()
def list_tables() -> list[str]:
    """List available tables in the business database."""

    with get_connection() as con:
        rows = con.execute("SHOW TABLES").fetchall()

    return [row[0] for row in rows]


@mcp.tool()
def describe_table(table_name: str) -> list[dict]:
    """Return column names and DuckDB data types for an allowed table."""

    allowed_tables = list_tables()

    if table_name not in allowed_tables:
        raise ValueError("Unknown table name")

    with get_connection() as con:
        rows = con.execute(f'DESCRIBE SELECT * FROM "{table_name}"').fetchall()

    return [{"column": row[0], "type": row[1]} for row in rows]


@mcp.tool()
def revenue_by_category() -> list[dict]:
    """Calculate all-time revenue and gross profit by product category."""

    query = """
        SELECT
            p.category,
            ROUND(SUM(o.quantity * p.price), 2)
                AS revenue,
            ROUND(
                SUM(o.quantity * (p.price - p.unit_cost)),
                2
            ) AS gross_profit
        FROM orders o
        JOIN products p
            ON o.product_id = p.product_id
        GROUP BY p.category
        ORDER BY revenue DESC
    """

    with get_connection() as con:
        rows = con.execute(query).fetchall()

    return [
        {
            "category": row[0],
            "revenue": row[1],
            "gross_profit": row[2],
        }
        for row in rows
    ]


@mcp.tool()
def execute_readonly_query(sql: str) -> dict:
    """Execute a validated, read-only analytical SQL query.

    Supports a single SELECT against the customers, products, and orders
    tables. Returns column names and at most 100 serialized result rows.
    """

    try:
        validated_sql = validate_sql(sql)
    except (TypeError, ValueError) as error:
        return {
            "error": str(error),
            "error_type": type(error).__name__,
            "sql": sql,
        }
    max_rows = 100

    try:
        with duckdb.connect(
            str(DB_PATH),
            read_only=True,
            config={
                "enable_external_access": "false",
                "memory_limit": "256MB",
                "threads": "2",
            },
        ) as con:
            result = con.execute(validated_sql)

            columns = [description[0] for description in result.description]

            # Fetch one extra row to detect truncation.
            records = result.fetchmany(max_rows + 1)
    except duckdb.Error as error:
        return {
            "error": str(error),
            "error_type": type(error).__name__,
            "sql": validated_sql,
        }

    truncated = len(records) > max_rows
    records = records[:max_rows]

    def serialize(value):
        """Convert a DuckDB value into a JSON-compatible scalar."""
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    rows = [
        {column: serialize(value) for column, value in zip(columns, record)}
        for record in records
    ]

    return {
        "columns": columns,
        "rows": rows,
        "returned_rows": len(rows),
        "truncated": truncated,
    }


if __name__ == "__main__":
    mcp.run()

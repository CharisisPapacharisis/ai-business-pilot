"""Validate model-generated SQL before it reaches the DuckDB MCP tool."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

ALLOWED_TABLES = {"customers", "products", "orders"}

ALLOWED_FUNCTIONS = {
    "SUM",
    "COUNT",
    "AVG",
    "MIN",
    "MAX",
    "ROUND",
    "DATE_TRUNC",
    "EXTRACT",
    "COALESCE",
}


def validate_sql(sql: str) -> str:
    """Validate and normalize a restricted DuckDB SELECT statement."""

    if not sql or not sql.strip():
        raise ValueError("SQL query cannot be empty")

    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except ParseError as exc:
        raise ValueError(f"Invalid SQL syntax: {exc}") from exc

    if len(statements) != 1 or statements[0] is None:
        raise ValueError("Only one SQL statement is allowed")

    statement = statements[0]

    if not isinstance(statement, exp.Select):
        raise TypeError("Only SELECT statements are allowed")

    # Keep the first version simple: no nested queries or CTEs.
    if any(
        isinstance(node, (exp.Subquery, exp.CTE, exp.Union))
        for node in statement.walk()
    ):
        raise ValueError("Subqueries, CTEs and UNION are not supported yet")

    for table in statement.find_all(exp.Table):
        if table.name.lower() not in ALLOWED_TABLES or table.db or table.catalog:
            raise ValueError(f"Table not allowed: {table.sql()}")

    for function in statement.find_all(exp.Func):
        if isinstance(function, (exp.Binary, exp.Unary, exp.Predicate)):
            continue
        if function.sql_name().upper() not in ALLOWED_FUNCTIONS:
            raise ValueError(f"SQL function not allowed: {function.sql_name()}")

    return statement.sql(dialect="duckdb")

"""Check DuckDB, Linear read, or Linear write MCP connectivity."""

import argparse
import asyncio
import json

from ai_business_pilot.mcp_client import create_mcp_adapter

SOURCES = ("duckdb", "linear-read", "linear-write")
WRITE_TOOL_NAMES = {
    "get_issue",
    "get_team",
    "list_issues",
    "list_teams",
    "save_issue",
}


def parse_args() -> argparse.Namespace:
    """Select the MCP endpoint to inspect."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=SOURCES)
    return parser.parse_args()


def find_tool(tools, name: str):
    """Find a tool with or without an MCP server-name prefix."""
    return next(
        (tool for tool in tools if tool.name == name or tool.name.endswith(f"_{name}")),
        None,
    )


async def check_duckdb() -> None:
    """Invoke representative read-only tools from the local MCP server."""
    adapter = create_mcp_adapter(include_duckdb=True)
    async with adapter:
        tools = await adapter.list_tools()
        print("\nAvailable DuckDB tools:")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")

        checks = (
            ("list_tables", {}),
            ("describe_table", {"table_name": "orders"}),
            (
                "execute_readonly_query",
                {
                    "sql": (
                        "SELECT p.category, SUM(o.quantity * p.price) AS revenue "
                        "FROM orders AS o JOIN products AS p "
                        "ON o.product_id = p.product_id GROUP BY p.category "
                        "ORDER BY revenue DESC"
                    )
                },
            ),
        )
        for name, arguments in checks:
            tool = find_tool(tools, name)
            if tool is None:
                raise RuntimeError(f"DuckDB MCP tool unavailable: {name}")
            print(f"\n{name}:\n{await tool.ainvoke(arguments)}")

    print("\nDuckDB MCP check passed.")


async def check_linear_read() -> None:
    """Connect to Linear's read-only endpoint and print tool schemas."""
    adapter = create_mcp_adapter(include_duckdb=False, include_linear=True)
    async with adapter:
        tools = await adapter.list_tools()

    print(f"Connected to Linear read MCP. Discovered {len(tools)} tools.")
    for tool in tools:
        print(f"\nTool: {tool.name}")
        print(f"Description: {tool.description}")
        print(f"Input schema: {tool.args_schema}")


async def check_linear_write() -> None:
    """Discover write-endpoint tools without invoking any of them."""
    adapter = create_mcp_adapter(
        include_duckdb=False,
        include_linear=False,
        include_linear_write=True,
    )
    async with adapter:
        tools = await adapter.list_tools()

    print(f"Connected to Linear write MCP. Discovered {len(tools)} tools.")
    for tool in tools:
        if any(
            tool.name == name or tool.name.endswith(f"_{name}")
            for name in WRITE_TOOL_NAMES
        ):
            print(f"\nTool: {tool.name}")
            print(f"Description: {tool.description}")
            print(json.dumps(tool.args, indent=2, default=str))

    save_issue = find_tool(tools, "save_issue")
    if save_issue is None:
        raise RuntimeError("Linear write endpoint did not expose save_issue")
    print(f"\nWrite capability confirmed: {save_issue.name}")
    print("No tools were invoked and no Linear data was changed.")


async def main() -> None:
    """Run the selected connection check."""
    source = parse_args().source
    checks = {
        "duckdb": check_duckdb,
        "linear-read": check_linear_read,
        "linear-write": check_linear_write,
    }
    await checks[source]()


if __name__ == "__main__":
    asyncio.run(main())

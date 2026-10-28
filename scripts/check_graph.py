"""Check routing and tool use across the complete analysis graph."""

import asyncio
import sys

from ai_business_pilot.fixture_config import (
    DEMO_PRODUCT_NAME,
    LINEAR_DEMO_ISSUE_TITLE,
)
from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.mcp_client import create_mcp_adapter

QUESTIONS = {
    "duckdb": (
        "Which product category generated the highest gross profit in September 2026?"
    ),
    "linear": (
        f"What is the current status of the {LINEAR_DEMO_ISSUE_TITLE} work "
        "item, and what change does it propose?"
    ),
    "both": (
        f"Evaluate the financial impact of the proposed {DEMO_PRODUCT_NAME} "
        f"change described in {LINEAR_DEMO_ISSUE_TITLE}. Compare current and "
        "proposed gross profit using historical sales volume, assuming unit "
        "cost and sales volume remain unchanged."
    ),
}


async def main() -> None:
    """Run one selected scenario while keeping both MCP connections open."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    adapter = create_mcp_adapter(
        include_duckdb=True,
        include_linear=True,
    )

    async with adapter:
        tools = await adapter.list_tools()

        duckdb_tool_count = sum(tool.name.startswith("duckdb_") for tool in tools)
        linear_tool_count = sum(tool.name.startswith("linear_") for tool in tools)

        print("\n--- DISCOVERED MCP TOOLS ---")
        print(f"DuckDB: {duckdb_tool_count}")
        print(f"Linear: {linear_tool_count}")

        graph = build_graph(tools)

        # Options: "duckdb", "linear", "both"
        scenario = "both"

        question = QUESTIONS[scenario]

        print("\n--- BUSINESS QUESTION ---")
        print(question)

        result = await graph.ainvoke(
            {"question": question},
            config={"recursion_limit": 30},
        )

        print("\n" + "=" * 60)
        print("LANGGRAPH ROUTING")
        print("=" * 60)

        print(f"Expected route: {scenario}")
        print(f"Selected route: {result['route']}")

        if result["route"] == scenario:
            print("Routing test PASSED")
        else:
            print("Routing test FAILED")

        print("\n" + "=" * 60)
        print("MCP TOOL EXECUTION")
        print("=" * 60)

        for call in result["tool_calls"]:
            print(f"- {call}")

        tool_calls_text = " ".join(result["tool_calls"])

        duckdb_used = "duckdb_" in tool_calls_text
        linear_used = "linear_" in tool_calls_text

        print(f"\nDuckDB used: {duckdb_used}")
        print(f"Linear used: {linear_used}")

        expected_usage = {
            "duckdb": (True, False),
            "linear": (False, True),
            "both": (True, True),
        }

        expected_duckdb, expected_linear = expected_usage[scenario]

        if duckdb_used == expected_duckdb and linear_used == expected_linear:
            print("Tool usage test PASSED")
        else:
            print("Tool usage test FAILED")

        print("\n" + "=" * 60)
        print("INTERNAL ANALYST FINDINGS")
        print("=" * 60)

        print(result["analysis"])

        print("\n" + "=" * 60)
        print("FINAL BUSINESS REPORT")
        print("=" * 60)

        print(result["final_answer"])


if __name__ == "__main__":
    asyncio.run(main())

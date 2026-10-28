"""Check whether cross-system scenario numbers are grounded in DuckDB."""

import asyncio
import sys

from ai_business_pilot.fixture_config import (
    DEMO_PRODUCT_NAME,
    LINEAR_DEMO_ISSUE_TITLE,
)
from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.mcp_client import create_mcp_adapter

QUESTION = f"""
Retrieve the proposed {DEMO_PRODUCT_NAME} change and demand scenarios from the
Linear initiative titled {LINEAR_DEMO_ISSUE_TITLE}. Then use all available
historical {DEMO_PRODUCT_NAME} orders in DuckDB, without adding a date filter,
to estimate revenue, total cost, and gross profit for the baseline and each
proposed demand scenario. Calculate every derived value with DuckDB.
"""

EXPECTED_VALUES = {
    "baseline gross profit": "2800",
    "0% gross profit": "3100",
    "5% revenue": "5985",
    "5% gross profit": "2945",
    "10% revenue": "5670",
    "10% gross profit": "2790",
}


async def main() -> None:
    """Run a live graph evaluation and fail on ungrounded expected values."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
    async with adapter:
        graph = build_graph(await adapter.list_tools())
        result = await graph.ainvoke(
            {"question": QUESTION},
            config={"recursion_limit": 40},
        )

    evidence = result.get("evidence", "")
    answer = result.get("final_answer", "")
    normalized_evidence = evidence.replace(",", "")
    normalized_answer = answer.replace(",", "")
    calls = "\n".join(result.get("tool_calls", []))

    checks = {
        "selected both sources": result.get("route") == "both",
        "queried Linear": "linear_" in calls,
        "queried DuckDB": "duckdb_" in calls,
        "analyst stayed within limits": "call limits exceeded"
        not in result.get("analysis", "").lower(),
        **{
            f"evidence contains {label}": value in normalized_evidence
            for label, value in EXPECTED_VALUES.items()
        },
        **{
            f"answer contains {label}": value in normalized_answer
            for label, value in EXPECTED_VALUES.items()
        },
    }

    print("\n" + "=" * 60)
    print("NUMERICAL GROUNDING EVALUATION")
    print("=" * 60)
    for check, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {check}")

    print("\nFinal answer:\n")
    print(answer)

    failed = [check for check, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Numerical grounding failed: {', '.join(failed)}")


if __name__ == "__main__":
    asyncio.run(main())

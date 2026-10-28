"""Compare one analysis prompt through direct graph and UI runtime entrypoints."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from langgraph.store.sqlite.aio import AsyncSqliteStore

from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.graph.state import BusinessContext
from ai_business_pilot.mcp_client import create_mcp_adapter
from ai_business_pilot.ui.runtime import UI_USER_ID, run_question

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_DB = PROJECT_ROOT / "storage" / "business_memory.sqlite"


def parse_args() -> argparse.Namespace:
    """Read one analysis-only question from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="The exact prompt to run through both paths")
    return parser.parse_args()


async def run_direct(question: str) -> dict:
    """Run the graph directly with the same tools, memory, and user identity."""
    adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
    async with (
        adapter,
        AsyncSqliteStore.from_conn_string(str(MEMORY_DB)) as store,
    ):
        await store.setup()
        graph = build_graph(await adapter.list_tools(), store=store)
        return await graph.ainvoke(
            {"question": question},
            config={"recursion_limit": 40},
            context=BusinessContext(user_id=UI_USER_ID),
        )


def summary(result: dict) -> dict:
    """Return the execution fields useful for entrypoint comparison."""
    return {
        "route": result.get("route"),
        "action": result.get("action"),
        "status": result.get("status"),
        "tool_calls": result.get("tool_calls", []),
        "analysis": result.get("analysis"),
        "final_answer": result.get("final_answer"),
    }


def main() -> None:
    """Execute both paths sequentially and print comparable JSON traces."""
    question = parse_args().question
    direct = asyncio.run(run_direct(question))
    ui_thread_id = f"ab-ui-{uuid4()}"
    ui = run_question(ui_thread_id, question)

    print("\nDIRECT GRAPH RESULT")
    print(json.dumps(summary(direct), indent=2, ensure_ascii=False))
    print("\nUI RUNTIME RESULT")
    print(json.dumps(summary(ui), indent=2, ensure_ascii=False))
    print(f"\nUI checkpoint thread: {ui_thread_id}")


if __name__ == "__main__":
    main()

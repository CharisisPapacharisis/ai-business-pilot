"""Demonstrate a two-turn conversation persisted by a SQLite checkpointer."""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ai_business_pilot.fixture_config import (
    DEMO_PRODUCT_NAME,
    LINEAR_DEMO_ISSUE_TITLE,
)
from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.mcp_client import create_mcp_adapter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_DB = PROJECT_ROOT / "storage" / "graph_checkpoints.sqlite"


def print_section(title: str) -> None:
    """Print a clear terminal section heading."""
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def main() -> None:
    """Run a follow-up question using state from the same thread."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    thread_id = f"persistence-demo-{uuid4()}"
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 30,
    }

    adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
    async with (
        adapter,
        AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as checkpointer,
    ):
        tools = await adapter.list_tools()
        graph = build_graph(tools, checkpointer=checkpointer)

        first_question = (
            f"What is the status of the {LINEAR_DEMO_ISSUE_TITLE} work item, "
            "and what does it propose?"
        )
        print_section("QUESTION RUN 1")
        print(f"Thread ID: {thread_id}\n")
        print(first_question)

        first = await graph.ainvoke(
            {"question": first_question},
            config=config,
        )
        print_section("OUTPUT OF QUESTION RUN 1")
        print(first["final_answer"])

        second_question = (
            f"What conclusion did we reach about the {DEMO_PRODUCT_NAME} proposal, "
            "and is it still awaiting approval?"
        )
        print_section("QUESTION RUN 2 (FOLLOW-UP)")
        print(second_question)

        second = await graph.ainvoke(
            {"question": second_question},
            config=config,
        )
        print_section("OUTPUT OF QUESTION RUN 2")
        print(second["final_answer"])

        print_section("SAVED CHECKPOINT HISTORY")
        print(f"Thread ID: {thread_id}")
        print(f"History entries: {len(second['history'])}")
        for number, entry in enumerate(second["history"], start=1):
            print(f"\n--- HISTORY ENTRY {number} ---\n{entry}")


if __name__ == "__main__":
    asyncio.run(main())

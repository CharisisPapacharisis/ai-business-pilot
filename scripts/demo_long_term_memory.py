"""Demonstrate explicit business memory shared across conversation threads."""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from ai_business_pilot.fixture_config import (
    DEMO_PRODUCT_NAME,
    LINEAR_DEMO_ISSUE_TITLE,
)
from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.graph.state import BusinessContext
from ai_business_pilot.mcp_client import create_mcp_adapter
from ai_business_pilot.memory import save_business_memory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_DB = PROJECT_ROOT / "storage" / "graph_checkpoints.sqlite"
MEMORY_DB = PROJECT_ROOT / "storage" / "business_memory.sqlite"


async def main() -> None:
    """Save a preference in one thread and use it from another thread."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    user_id = f"memory-test-{uuid4()}"
    source_thread_id = f"memory-source-{uuid4()}"
    analysis_thread_id = f"memory-reader-{uuid4()}"

    adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
    async with (
        adapter,
        AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as checkpointer,
        AsyncSqliteStore.from_conn_string(str(MEMORY_DB)) as store,
    ):
        await store.setup()
        # Arrange one controlled fixture; production memories are not defined here.
        await save_business_memory(
            store,
            user_id=user_id,
            key="test-pricing-demand-scenarios",
            content="Use demand reductions of 0%, 5%, and 10% in this test.",
            category="test_fixture",
            source=f"test setup in thread {source_thread_id}",
        )

        tools = await adapter.list_tools()
        graph = build_graph(tools, checkpointer=checkpointer, store=store)
        question = (
            f"Evaluate the financial impact of the {DEMO_PRODUCT_NAME} change "
            f"in the {LINEAR_DEMO_ISSUE_TITLE} proposal using our usual demand "
            "scenarios."
        )
        config = {
            "configurable": {"thread_id": analysis_thread_id},
            "recursion_limit": 30,
        }

        print("\n" + "=" * 60)
        print("CROSS-THREAD MEMORY TEST")
        print("=" * 60)
        print(f"User: {user_id}")
        print(f"Memory source thread: {source_thread_id}")
        print(f"Analysis thread: {analysis_thread_id}")
        print(f"Question: {question}")

        result = await graph.ainvoke(
            {"question": question},
            config=config,
            context=BusinessContext(user_id=user_id),
        )

        print("\n" + "=" * 60)
        print("RETRIEVED LONG-TERM MEMORY")
        print("=" * 60)
        for memory in result.get("memories", []):
            print(f"- {memory}")

        print("\n" + "=" * 60)
        print("FINAL ANSWER")
        print("=" * 60)
        print(result["final_answer"])


if __name__ == "__main__":
    asyncio.run(main())

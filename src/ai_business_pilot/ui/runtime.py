"""Operation-scoped LangGraph runtime used by the Streamlit interface."""

import asyncio
import os
import threading
from collections import defaultdict
from contextlib import AsyncExitStack
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langgraph.types import Command

from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.graph.state import BusinessContext
from ai_business_pilot.mcp_client import create_mcp_adapter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT_DB = PROJECT_ROOT / "storage" / "graph_checkpoints.sqlite"
MEMORY_DB = PROJECT_ROOT / "storage" / "business_memory.sqlite"
UI_USER_ID = "streamlit-local-user"
RUN_TIMEOUT_SECONDS = float(os.getenv("AI_PILOT_RUN_TIMEOUT_SECONDS", "600"))

_THREAD_LOCKS: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


async def _load_thread_state(thread_id: str) -> dict:
    """Read the latest checkpoint without connecting to any MCP server."""
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        saved = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
    return dict(saved.checkpoint["channel_values"]) if saved else {}


async def _execute(
    thread_id: str,
    graph_input: dict | Command | None,
    *,
    include_write_tools: bool,
) -> dict:
    """Open resources for one graph operation and return persisted state."""
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB))
        )
        store = await stack.enter_async_context(
            AsyncSqliteStore.from_conn_string(str(MEMORY_DB))
        )
        await store.setup()

        read_adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
        await stack.enter_async_context(read_adapter)
        read_tools = await read_adapter.list_tools()

        action_tools = []
        if include_write_tools:
            write_adapter = create_mcp_adapter(
                include_duckdb=False,
                include_linear=False,
                include_linear_write=True,
            )
            await stack.enter_async_context(write_adapter)
            action_tools = read_tools + await write_adapter.list_tools()

        graph = build_graph(
            read_tools,
            checkpointer=checkpointer,
            store=store,
            action_tools=action_tools,
        )
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 40,
        }
        await asyncio.wait_for(
            graph.ainvoke(
                graph_input,
                config=config,
                context=BusinessContext(user_id=UI_USER_ID),
            ),
            timeout=RUN_TIMEOUT_SECONDS,
        )
        snapshot = await graph.aget_state(config)
        return dict(snapshot.values)


def _run_locked(thread_id: str, coroutine) -> dict:
    """Run one async operation while rejecting duplicate same-thread actions."""
    lock = _THREAD_LOCKS[thread_id]
    if not lock.acquire(blocking=False):
        coroutine.close()
        raise RuntimeError("This conversation already has an active run")
    try:
        return asyncio.run(coroutine)
    finally:
        lock.release()


def load_thread_state(thread_id: str) -> dict:
    """Synchronously load one thread for Streamlit rendering."""
    return _run_locked(thread_id, _load_thread_state(thread_id))


def run_question(thread_id: str, question: str) -> dict:
    """Run a new conversational turn with read-only analyst tools."""
    return _run_locked(
        thread_id,
        _execute(thread_id, {"question": question}, include_write_tools=False),
    )


def resume_action(thread_id: str, approved: bool, *, retry: bool = False) -> dict:
    """Resume a saved interrupt, opening write tools only for approval."""
    graph_input = None if retry else Command(resume={"approved": approved})
    return _run_locked(
        thread_id,
        _execute(
            thread_id,
            graph_input,
            include_write_tools=approved,
        ),
    )

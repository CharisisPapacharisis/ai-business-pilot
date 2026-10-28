"""Verify checkpoint, same-thread, and cross-thread memory after issue creation."""

import argparse
import asyncio
from contextlib import aclosing
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.graph.state import BusinessContext
from ai_business_pilot.mcp_client import create_mcp_adapter
from ai_business_pilot.memory import save_business_memory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_DB = PROJECT_ROOT / "storage" / "graph_checkpoints.sqlite"
MEMORY_DB = PROJECT_ROOT / "storage" / "business_memory.sqlite"


def parse_args() -> argparse.Namespace:
    """Select one persistence layer to verify."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("checkpoint", "Inspect the saved action outcome without MCP calls"),
        ("conversation", "Ask a follow-up in the original thread"),
        ("memory", "Record the outcome and retrieve it in a new thread"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "thread_id",
            nargs="?",
            help="Completed issue-workflow thread; defaults to the latest one",
        )
        if name == "memory":
            command.add_argument("--user-id", default="business-analyst-demo")
    return parser.parse_args()


def heading(title: str) -> None:
    """Print a visible terminal section."""
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def completed_issue(values: dict) -> dict:
    """Validate and return a checkpointed successful action outcome."""
    if values.get("status") == "created_verified":
        approved = values.get("approved")
        issue = values.get("created_issue")
    else:
        outcome = next(
            (
                item
                for item in reversed(values.get("action_outcomes", []))
                if item.get("status") == "created_verified"
            ),
            None,
        )
        if outcome is None:
            raise AssertionError("No verified issue creation exists in this thread")
        approved = outcome.get("approved")
        issue = outcome.get("issue")
    if approved is not True:
        raise AssertionError("The saved action is not explicitly approved")
    if not isinstance(issue, dict) or not issue:
        raise AssertionError("The checkpoint has no created Linear issue")
    if not any(issue.get(key) for key in ("id", "identifier", "url")):
        raise AssertionError("The saved Linear issue has no ID, identifier, or URL")
    return issue


def issue_reference(issue: dict) -> str:
    """Return the most useful human-facing issue reference."""
    return str(issue.get("identifier") or issue.get("id") or issue.get("url"))


async def find_thread(checkpointer, requested: str | None) -> tuple[str, dict]:
    """Load an explicit thread or find the latest completed issue workflow."""
    if requested:
        saved = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": requested}}
        )
        if saved is None:
            raise ValueError(f"No checkpoint found for {requested!r}")
        values = saved.checkpoint["channel_values"]
        completed_issue(values)
        return requested, values

    seen = set()
    async with aclosing(checkpointer.alist(None, limit=200)) as checkpoints:
        async for saved in checkpoints:
            thread_id = saved.config["configurable"]["thread_id"]
            if thread_id in seen:
                continue
            seen.add(thread_id)
            values = saved.checkpoint["channel_values"]
            try:
                completed_issue(values)
            except AssertionError:
                continue
            return thread_id, values
    raise ValueError("No completed issue-workflow checkpoint was found")


def show_checkpoint(thread_id: str, values: dict) -> None:
    """Display the durable workflow fields under one thread."""
    issue = completed_issue(values)
    heading("GRAPH CHECKPOINT VERIFIED")
    print(f"Thread ID: {thread_id}")
    print("Saved action status: created_verified")
    print("Approved: True")
    print(f"Issue reference: {issue_reference(issue)}")
    print(f"Issue title: {issue.get('title', 'not returned')}")
    print(f"History entries: {len(values.get('history', []))}")
    print(f"Recorded action outcomes: {len(values.get('action_outcomes', []))}")


async def verify_conversation(thread_id: str, values: dict, checkpointer) -> None:
    """Run a contextual follow-up and confirm it extends the same thread."""
    issue = completed_issue(values)
    previous_history = values.get("history", [])
    adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
    async with adapter:
        tools = await adapter.list_tools()
        graph = build_graph(tools, checkpointer=checkpointer)
        result = await graph.ainvoke(
            {
                "question": (
                    "What happened to the Linear issue we just proposed? "
                    "Include its identifier and current status."
                )
            },
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 40,
            },
        )

    if len(result.get("history", [])) <= len(previous_history):
        raise AssertionError("The follow-up did not extend the existing thread history")
    expected = [issue_reference(issue), str(issue.get("title", ""))]
    answer = result.get("final_answer", "").casefold()
    if not any(value and value.casefold() in answer for value in expected):
        raise AssertionError(
            "The follow-up did not identify the previously created issue"
        )

    heading("SAME-THREAD FOLLOW-UP VERIFIED")
    print(f"Thread ID: {thread_id}")
    print(f"History entries before: {len(previous_history)}")
    print(f"History entries after: {len(result['history'])}")
    print("\nFollow-up answer:")
    print(result["final_answer"])


async def verify_long_term_memory(
    thread_id: str,
    values: dict,
    checkpointer,
    user_id: str,
) -> None:
    """Explicitly record the creation event and retrieve it in another thread."""
    issue = completed_issue(values)
    reference = issue_reference(issue)
    title = str(issue.get("title", "Untitled Linear issue"))
    content = f"Created Linear issue {reference}: {title}."
    new_thread_id = f"issue-memory-reader-{uuid4()}"

    adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
    async with (
        adapter,
        AsyncSqliteStore.from_conn_string(str(MEMORY_DB)) as store,
    ):
        await store.setup()
        await save_business_memory(
            store,
            user_id=user_id,
            key=f"created-linear-issue-{reference}",
            content=content,
            category="action_outcome",
            source=f"explicitly recorded from thread {thread_id}",
        )
        tools = await adapter.list_tools()
        graph = build_graph(tools, checkpointer=checkpointer, store=store)
        result = await graph.ainvoke(
            {
                "question": (
                    "Which Linear issue creation outcome have I asked you to remember?"
                )
            },
            config={
                "configurable": {"thread_id": new_thread_id},
                "recursion_limit": 40,
            },
            context=BusinessContext(user_id=user_id),
        )

    memories = result.get("memories", [])
    if not any(reference in memory for memory in memories):
        raise AssertionError("The new thread did not retrieve the recorded outcome")

    heading("CROSS-THREAD MEMORY VERIFIED")
    print(f"Source thread: {thread_id}")
    print(f"Reader thread: {new_thread_id}")
    print(f"User ID: {user_id}")
    print(f"Retrieved memory: {content}")
    print("\nNew-thread answer:")
    print(result["final_answer"])


async def main() -> None:
    """Verify the requested persistence layer for a completed issue workflow."""
    args = parse_args()
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as checkpointer:
        thread_id, values = await find_thread(checkpointer, args.thread_id)
        if args.command == "checkpoint":
            show_checkpoint(thread_id, values)
        elif args.command == "conversation":
            await verify_conversation(thread_id, values, checkpointer)
        else:
            await verify_long_term_memory(
                thread_id,
                values,
                checkpointer,
                args.user_id,
            )


if __name__ == "__main__":
    asyncio.run(main())

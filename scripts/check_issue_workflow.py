"""Check the analysis-to-approved-Linear-issue acceptance workflow."""

import argparse
import asyncio
import json
from contextlib import aclosing
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from ai_business_pilot.graph.builder import build_graph
from ai_business_pilot.mcp_client import create_mcp_adapter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_DB = PROJECT_ROOT / "storage" / "graph_checkpoints.sqlite"
ACCEPTANCE_REQUEST = (
    "Identify the product with the lowest gross profit, check whether an existing "
    "Linear initiative addresses it, and if not, propose a new issue with your "
    "findings."
)


def parse_args() -> argparse.Namespace:
    """Parse the start or resume workflow command."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Analyze, draft, and pause")
    start.add_argument("--thread-id", default=None)
    resume = commands.add_parser("resume", help="Approve or reject a paused draft")
    resume.add_argument("thread_id", nargs="?")
    resume.add_argument("decision", nargs="?", choices=("approve", "reject"))
    return parser.parse_args()


def heading(title: str) -> None:
    """Print a visible terminal section."""
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def latest_paused_thread_id(checkpointer) -> str:
    """Find the newest unfinished issue workflow from raw checkpoint state."""
    seen = set()
    unfinished_statuses = {
        "pending_approval",
        "approved",
        "created_pending_verification",
    }
    async with aclosing(checkpointer.alist(None, limit=500)) as checkpoints:
        async for checkpoint in checkpoints:
            thread_id = checkpoint.config["configurable"]["thread_id"]
            if thread_id in seen or not thread_id.startswith("issue-workflow-"):
                continue
            seen.add(thread_id)
            values = checkpoint.checkpoint["channel_values"]
            if values.get("status") in unfinished_statuses:
                return thread_id
    raise ValueError("No paused issue workflow was found")


def prompt_for_decision() -> str:
    """Collect an explicit terminal approval decision."""
    while True:
        choice = input("\nCreate this Linear issue? (y/n): ").strip().casefold()
        if choice in {"y", "yes"}:
            return "approve"
        if choice in {"n", "no"}:
            return "reject"
        print("Please enter y or n.")


def show_draft(thread_id: str, payload: dict) -> None:
    """Show the complete draft awaiting authorization."""
    heading("LINEAR ISSUE APPROVAL REQUIRED")
    print(f"Thread ID: {thread_id}")
    print(json.dumps(payload, indent=2, default=str))
    print("\nResume interactively with:")
    print("uv run python scripts/check_issue_workflow.py resume")


def show_result(thread_id: str, result: dict) -> None:
    """Print the persisted analysis and external-action outcome."""
    heading("WORKFLOW RESULT")
    print(f"Thread ID: {thread_id}")
    print(f"Route: {result.get('route')}")
    print(f"Action: {result.get('action')}")
    print(f"Status: {result.get('status')}")
    print(f"Approved: {result.get('approved')}")
    print(f"Tool calls: {len(result.get('tool_calls', []))}")
    if result.get("created_issue"):
        print("\nCreated/verified Linear issue:")
        print(json.dumps(result["created_issue"], indent=2, default=str))
    print("\nFinal answer:")
    print(result.get("final_answer", "No final answer was produced."))


def verify_analysis_path(result: dict) -> None:
    """Assert that the acceptance analysis used both required systems."""
    calls = " ".join(result.get("tool_calls", []))
    if result.get("route") != "both":
        raise AssertionError(f"Expected route 'both', got {result.get('route')!r}")
    if "duckdb_" not in calls or "linear_" not in calls:
        raise AssertionError("Acceptance analysis did not use DuckDB and Linear")
    if result.get("action") != "draft_issue":
        raise AssertionError("Acceptance request was not classified as an action")


async def verify_persisted_outcome(graph, config: dict, result: dict) -> None:
    """Confirm the terminal action outcome is checkpointed on this thread."""
    snapshot = await graph.aget_state(config)
    if snapshot.values.get("status") != result.get("status"):
        raise AssertionError("Action outcome was not saved in the current thread")


async def main() -> None:
    """Execute or resume the durable end-to-end acceptance scenario."""
    args = parse_args()
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as checkpointer:
        if args.command == "resume":
            print("[CHECKPOINT] Locating the paused issue workflow...")
            thread_id = args.thread_id or await latest_paused_thread_id(checkpointer)
            print(f"[CHECKPOINT] Selected thread: {thread_id}")

        print("[MCP] Connecting to DuckDB and read-only Linear...")
        read_adapter = create_mcp_adapter(include_duckdb=True, include_linear=True)
        async with read_adapter:
            read_tools = await read_adapter.list_tools()
            print(f"[MCP] Discovered {len(read_tools)} read tools.")
            graph = build_graph(read_tools, checkpointer=checkpointer)

            if args.command == "start":
                thread_id = args.thread_id or f"issue-workflow-{uuid4()}"
                config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 40,
                }
                heading("ACCEPTANCE REQUEST")
                print(ACCEPTANCE_REQUEST)
                result = await graph.ainvoke({"question": ACCEPTANCE_REQUEST}, config)
                verify_analysis_path(result)
                interrupts = result.get("__interrupt__", [])
                if interrupts:
                    show_draft(thread_id, interrupts[0].value)
                else:
                    show_result(thread_id, result)
                return

            config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 40,
            }
            print("[CHECKPOINT] Loading the selected graph state...")
            snapshot = await graph.aget_state(config)
            if not snapshot.next:
                raise ValueError(f"No pending workflow found for {thread_id!r}")

            if snapshot.values.get("approved") is True:
                decision = "approve"
                graph_input = None
                heading("RETRYING PREVIOUSLY APPROVED ACTION")
                print("No new approval is requested.")
            else:
                interrupt_payload = snapshot.interrupts[0].value
                show_draft(thread_id, interrupt_payload)
                decision = args.decision or prompt_for_decision()
                graph_input = Command(resume={"approved": decision == "approve"})

            if decision == "reject":
                result = await graph.ainvoke(graph_input, config)
                if result.get("created_issue") is not None:
                    raise AssertionError(
                        "Rejection unexpectedly recorded a created issue"
                    )
                await verify_persisted_outcome(graph, config, result)
                show_result(thread_id, result)
                return

            print("[MCP] Approval confirmed; connecting to Linear write tools...")
            write_adapter = create_mcp_adapter(
                include_duckdb=False,
                include_linear=False,
                include_linear_write=True,
            )
            async with write_adapter:
                write_tools = await write_adapter.list_tools()
                print(f"[MCP] Discovered {len(write_tools)} write-endpoint tools.")
                graph = build_graph(
                    read_tools,
                    checkpointer=checkpointer,
                    action_tools=read_tools + write_tools,
                )
                result = await graph.ainvoke(graph_input, config)
                if result.get("status") != "created_verified":
                    raise AssertionError("Approved issue was not created and verified")
                await verify_persisted_outcome(graph, config, result)
            show_result(thread_id, result)


if __name__ == "__main__":
    asyncio.run(main())

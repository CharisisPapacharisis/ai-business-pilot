"""Integration tests for approved and duplicate-aware issue creation."""

import asyncio
import json

import pytest
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ai_business_pilot.approval import (
    LinearIssueDraft,
    build_approval_graph,
    create_execute_node,
)


def issue_draft() -> dict:
    """Return one validated test draft."""
    return LinearIssueDraft(
        request_id="request-1234",
        title="[Demo request-1234] Review profitability",
        description="Validate the approved issue creation workflow.",
        team="Business Operations",
        proposed_priority=3,
        supporting_evidence=["This is fictional test evidence."],
    ).model_dump()


def fake_linear_tools(existing: list[dict], created: list[dict]):
    """Build deterministic read and write tools around in-memory issues."""

    @tool("linear_list_issues")
    async def list_issues(query: str) -> str:
        """Search fake Linear issues."""
        matches = [
            issue for issue in existing if query.casefold() in issue["title"].casefold()
        ]
        return json.dumps({"issues": matches})

    @tool("linear_write_save_issue")
    async def save_issue(
        title: str,
        description: str,
        team: str,
        priority: int,
    ) -> str:
        """Create one fake Linear issue."""
        issue = {
            "id": f"OPS-{len(existing) + 1}",
            "title": title,
            "description": description,
            "team": team,
            "priority": priority,
        }
        created.append(issue)
        existing.append(issue)
        return json.dumps(issue)

    @tool("linear_get_issue")
    async def get_issue(id: str) -> str:
        """Retrieve one fake Linear issue by ID."""
        issue = next(issue for issue in existing if issue["id"] == id)
        return json.dumps(issue)

    return [list_issues, get_issue, save_issue]


@pytest.mark.parametrize(
    ("approved", "expected_status"),
    [(True, "created_verified"), (False, "rejected")],
)
def test_approval_graph_pauses_then_resumes(
    approved: bool,
    expected_status: str,
) -> None:
    async def scenario() -> None:
        existing = []
        created = []
        tools = fake_linear_tools(existing, created)
        graph = build_approval_graph(InMemorySaver(), tools)
        config = {"configurable": {"thread_id": f"approval-{approved}"}}

        paused = await graph.ainvoke({"draft": issue_draft()}, config=config)
        payload = paused["__interrupt__"][0].value
        assert payload["draft"] == issue_draft()

        completed = await graph.ainvoke(
            Command(resume={"approved": approved}),
            config=config,
        )
        assert completed["approved"] is approved
        assert completed["status"] == expected_status
        assert len(created) == int(approved)

    asyncio.run(scenario())


def test_execute_node_requires_explicit_approval() -> None:
    execute_node = create_execute_node([])
    with pytest.raises(PermissionError, match="explicit approval"):
        asyncio.run(
            execute_node(
                {
                    "draft": issue_draft(),
                    "approved": False,
                }
            )
        )


def test_existing_exact_issue_is_reused_without_duplicate_write() -> None:
    async def scenario() -> None:
        draft = issue_draft()
        existing = [{"id": "OPS-7", "title": draft["title"]}]
        created = []
        execute_node = create_execute_node(fake_linear_tools(existing, created))

        result = await execute_node({"draft": draft, "approved": True})

        assert result["status"] == "duplicate_reused"
        assert result["created_issue"]["id"] == "OPS-7"
        assert created == []

    asyncio.run(scenario())

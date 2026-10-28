"""Unit tests for composed MCP-backed tools."""

import asyncio
import json

import pytest
from langchain_core.tools import tool

from ai_business_pilot.mcp_tools import (
    create_linear_find_issue_tool,
    find_mcp_tool,
)


def test_find_mcp_tool_accepts_server_prefix() -> None:
    @tool("linear_get_issue")
    def get_issue(issue_id: str) -> str:
        """Return an issue."""
        return issue_id

    assert find_mcp_tool([get_issue], "get_issue") is get_issue


def test_find_mcp_tool_reports_missing_dependency() -> None:
    with pytest.raises(ValueError, match="list_issues"):
        find_mcp_tool([], "list_issues")


def test_linear_find_issue_searches_before_retrieving_real_id() -> None:
    retrieved_ids = []

    @tool("linear_list_issues")
    async def list_issues(query: str) -> str:
        """Search issues."""
        assert query == "Electronics Pricing Optimization"
        return json.dumps(
            {"issues": [{"id": "OPS-4", "title": "Electronics Pricing Optimization"}]}
        )

    @tool("linear_get_issue")
    async def get_issue(id: str) -> str:
        """Retrieve an issue."""
        retrieved_ids.append(id)
        return json.dumps({"id": id, "status": "In Progress"})

    find_issue = create_linear_find_issue_tool([list_issues, get_issue])
    result = asyncio.run(
        find_issue.ainvoke({"query": "Electronics Pricing Optimization"})
    )

    assert retrieved_ids == ["OPS-4"]
    assert '"id": "OPS-4"' in result


def test_linear_find_issue_does_not_guess_when_search_is_ambiguous() -> None:
    get_issue_called = False

    @tool("linear_list_issues")
    async def list_issues(query: str) -> str:
        """Search issues."""
        return json.dumps(
            {
                "issues": [
                    {"id": "OPS-1", "title": f"{query} A"},
                    {"id": "OPS-2", "title": f"{query} B"},
                ]
            }
        )

    @tool("linear_get_issue")
    async def get_issue(id: str) -> str:
        """Retrieve an issue."""
        nonlocal get_issue_called
        get_issue_called = True
        return id

    find_issue = create_linear_find_issue_tool([list_issues, get_issue])
    result = asyncio.run(find_issue.ainvoke({"query": "Pricing"}))

    assert "Several Linear issues matched" in result
    assert get_issue_called is False

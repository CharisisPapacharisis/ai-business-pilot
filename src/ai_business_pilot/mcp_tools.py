"""Compose safer application tools from low-level MCP tools."""

import json

from langchain_core.tools import BaseTool, tool


def find_mcp_tool(tools: list[BaseTool], logical_name: str) -> BaseTool:
    """Find an MCP tool whether or not its server prefix is present."""
    match = next(
        (
            candidate
            for candidate in tools
            if candidate.name == logical_name
            or candidate.name.endswith(f"_{logical_name}")
        ),
        None,
    )
    if match is None:
        raise ValueError(f"Required MCP tool unavailable: {logical_name}")
    return match


def _text_content(result: object) -> str:
    """Extract text from an MCP-backed LangChain tool result."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = [
            block["text"]
            for block in result
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        if parts:
            return "\n".join(parts)
    raise ValueError("MCP tool returned no text content")


def create_linear_find_issue_tool(tools: list[BaseTool]) -> BaseTool:
    """Create a title-based lookup that resolves a real ID before retrieval."""
    list_issues = find_mcp_tool(tools, "list_issues")
    get_issue = find_mcp_tool(tools, "get_issue")

    @tool("linear_find_issue")
    async def find_linear_issue(query: str) -> str:
        """Find and retrieve a Linear issue by approximate title or keywords."""
        search_result = await list_issues.ainvoke({"query": query})
        search_payload = json.loads(_text_content(search_result))
        issues = search_payload.get("issues", [])
        if not issues:
            return f"No Linear issue found for {query!r}."

        exact_match = next(
            (
                candidate
                for candidate in issues
                if candidate.get("title", "").strip().casefold()
                == query.strip().casefold()
            ),
            None,
        )
        if exact_match is not None:
            issue = exact_match
        elif len(issues) == 1:
            issue = issues[0]
        else:
            candidates = [
                {"id": candidate.get("id"), "title": candidate.get("title")}
                for candidate in issues[:5]
            ]
            return (
                f"Several Linear issues matched {query!r}. "
                "Retry with more specific title words. "
                f"Candidates: {json.dumps(candidates)}"
            )

        issue_result = await get_issue.ainvoke({"id": issue["id"]})
        return _text_content(issue_result)

    return find_linear_issue

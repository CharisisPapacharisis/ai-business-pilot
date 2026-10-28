"""Tests for generic analyst execution safeguards."""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from ai_business_pilot.evidence import compact_evidence, content_text
from ai_business_pilot.graph.agent_safety import (
    prevent_duplicate_tool_call,
    require_empty_result_verification,
)
from mcp_servers.duckdb_server import execute_readonly_query


def test_readonly_query_returns_validation_details() -> None:
    result = execute_readonly_query("DELETE FROM products")

    assert result["error_type"] == "TypeError"
    assert result["error"] == "Only SELECT statements are allowed"
    assert result["sql"] == "DELETE FROM products"


def test_duplicate_tool_call_is_blocked() -> None:
    earlier = {
        "name": "duckdb_execute_readonly_query",
        "args": {"sql": "SELECT * FROM products"},
        "id": "first-call",
        "type": "tool_call",
    }
    repeated = {**earlier, "id": "second-call"}
    request = SimpleNamespace(
        tool_call=repeated,
        state={"messages": [AIMessage(content="", tool_calls=[earlier, repeated])]},
    )
    executed = False

    async def handler(_request):
        nonlocal executed
        executed = True
        return ToolMessage(content="executed", tool_call_id="second-call")

    result = asyncio.run(prevent_duplicate_tool_call(request, handler))

    assert result.status == "error"
    assert "Duplicate tool call blocked" in result.content
    assert executed is False


def test_changed_tool_arguments_are_allowed() -> None:
    earlier = {
        "name": "duckdb_execute_readonly_query",
        "args": {"sql": "SELECT * FROM products"},
        "id": "first-call",
        "type": "tool_call",
    }
    corrected = {
        **earlier,
        "args": {"sql": "SELECT COUNT(*) FROM products"},
        "id": "second-call",
    }
    request = SimpleNamespace(
        tool_call=corrected,
        state={"messages": [AIMessage(content="", tool_calls=[earlier, corrected])]},
    )

    async def handler(_request):
        return ToolMessage(content="executed", tool_call_id="second-call")

    result = asyncio.run(prevent_duplicate_tool_call(request, handler))

    assert result.content == "executed"


def test_content_text_removes_mcp_wrapper_metadata() -> None:
    content = [
        {"type": "text", "text": '{"value": 42}', "id": "internal-id"},
        {"type": "text", "text": "second result", "id": "another-id"},
    ]

    assert content_text(content) == '{"value": 42}\nsecond result'


def test_compact_evidence_prioritizes_final_calculation_and_linear_result() -> None:
    items = [
        "duckdb_list_tables: " + "table " * 400,
        "duckdb_describe_table: " + "schema " * 400,
        "linear_find_issue: proposal status and description",
        "duckdb_execute_readonly_query: final verified scenario values",
    ]

    compacted = compact_evidence(items, max_chars=300)

    assert len(compacted) <= 300
    assert "proposal status and description" in compacted
    assert "final verified scenario values" in compacted


def test_empty_query_result_requires_verification() -> None:
    request = SimpleNamespace(
        tool_call={
            "name": "duckdb_execute_readonly_query",
            "args": {"sql": "SELECT * FROM products WHERE category = 'Headphones'"},
            "id": "empty-call",
        }
    )

    async def handler(_request):
        return ToolMessage(
            content='{"columns": ["product_name"], "rows": [], "returned_rows": 0}',
            tool_call_id="empty-call",
        )

    result = asyncio.run(require_empty_result_verification(request, handler))

    assert result.status == "error"
    assert "UNVERIFIED_EMPTY_RESULT" in result.content
    assert "not proof" in result.content


def test_nonempty_query_result_remains_successful() -> None:
    request = SimpleNamespace(
        tool_call={
            "name": "duckdb_execute_readonly_query",
            "args": {"sql": "SELECT * FROM products"},
            "id": "nonempty-call",
        }
    )

    async def handler(_request):
        return ToolMessage(
            content=(
                '{"columns": ["product_name"], '
                '"rows": [{"product_name": "Headphones"}], "returned_rows": 1}'
            ),
            tool_call_id="nonempty-call",
        )

    result = asyncio.run(require_empty_result_verification(request, handler))

    assert result.status == "success"
    assert "UNVERIFIED_EMPTY_RESULT" not in result.content

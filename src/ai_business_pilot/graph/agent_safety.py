"""Runtime safeguards shared by all LangChain analyst agents.

These controls bound agent work, stop exact retries, and prevent an empty
query from becoming an unsupported absence claim.
"""

import json

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    wrap_tool_call,
)
from langchain_core.messages import ToolMessage

from ai_business_pilot.evidence import UNVERIFIED_EMPTY_RESULT, content_text


async def prevent_duplicate_tool_call(request, handler):
    """Block an exact retry while still allowing corrected arguments."""
    current = request.tool_call
    signature = (current["name"], json.dumps(current.get("args", {}), sort_keys=True))

    for message in request.state.get("messages", []):
        for earlier in getattr(message, "tool_calls", []):
            earlier_signature = (
                earlier["name"],
                json.dumps(earlier.get("args", {}), sort_keys=True),
            )
            if (
                earlier.get("id") != current.get("id")
                and earlier_signature == signature
            ):
                return ToolMessage(
                    content=(
                        "Duplicate tool call blocked. Review the prior result and "
                        "change the arguments before retrying."
                    ),
                    tool_call_id=current["id"],
                    name=current["name"],
                    status="error",
                )

    return await handler(request)


async def require_empty_result_verification(request, handler):
    """Make the agent verify identifiers after a zero-row DuckDB query."""
    result = await handler(request)
    tool_name = request.tool_call["name"]
    if not tool_name.endswith("execute_readonly_query") or not isinstance(
        result, ToolMessage
    ):
        return result

    text = content_text(result.content)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return result

    if payload.get("returned_rows") != 0 or payload.get("rows") != []:
        return result

    return ToolMessage(
        content=(
            f"{text}\n\n{UNVERIFIED_EMPTY_RESULT}: Zero rows are not proof that "
            "the requested entity or data does not exist. Verify likely identifier "
            "columns and distinct values, then retry with changed arguments before "
            "making an absence claim."
        ),
        tool_call_id=request.tool_call["id"],
        name=tool_name,
        status="error",
    )


DUPLICATE_TOOL_CALL_GUARD = wrap_tool_call(prevent_duplicate_tool_call)
EMPTY_RESULT_GUARD = wrap_tool_call(require_empty_result_verification)


def analyst_middleware() -> list:
    """Return the ordered safeguards applied to every analyst agent."""
    return [
        DUPLICATE_TOOL_CALL_GUARD,
        EMPTY_RESULT_GUARD,
        ToolCallLimitMiddleware(run_limit=10, exit_behavior="end"),
        ModelCallLimitMiddleware(run_limit=8, exit_behavior="end"),
    ]

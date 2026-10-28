"""Human approval workflow for guarded Linear issue creation."""

import json
from typing import Literal, NotRequired, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt
from pydantic import BaseModel, ConfigDict, Field

from ai_business_pilot.mcp_tools import find_mcp_tool


class LinearIssueDraft(BaseModel):
    """Validated issue content that remains unchanged after approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=8)
    title: str = Field(min_length=5, max_length=255)
    description: str = Field(min_length=10)
    team: str = Field(min_length=1)
    proposed_priority: int = Field(default=3, ge=0, le=4)
    supporting_evidence: list[str] = Field(min_length=1)

    def approved_description(self) -> str:
        """Render the exact description sent after approval."""
        evidence = "\n".join(f"- {item}" for item in self.supporting_evidence)
        return (
            f"{self.description}\n\nSupporting evidence:\n{evidence}\n\n"
            f"AI Business Pilot request: {self.request_id}"
        )


class ApprovalState(TypedDict):
    """Durable state for one approved or rejected issue draft."""

    draft: dict
    approved: NotRequired[bool]
    status: NotRequired[str]
    created_issue: NotRequired[dict]


def prepare_node(state: ApprovalState) -> dict:
    """Validate and normalize the draft before it reaches the human."""
    draft = LinearIssueDraft.model_validate(state["draft"])
    return {"draft": draft.model_dump(), "status": "pending_approval"}


def approval_node(state: ApprovalState) -> dict:
    """Pause and expose the complete immutable draft for human review."""
    draft = LinearIssueDraft.model_validate(state["draft"])
    decision = interrupt(
        {
            "action": "create_linear_issue",
            "draft": draft.model_dump(),
            "final_description": draft.approved_description(),
            "message": "Approve creating this Linear issue?",
        }
    )
    approved = isinstance(decision, dict) and decision.get("approved") is True
    return {
        "approved": approved,
        "status": "approved" if approved else "rejected",
    }


def approval_router(state: ApprovalState) -> Literal["execute", "reject"]:
    """Route from the persisted human decision."""
    return "execute" if state.get("approved") is True else "reject"


def reject_node(_: ApprovalState) -> dict:
    """Finish without executing the external action."""
    print("\n[ACTION] Request rejected; no Linear issue was created.")
    return {"status": "rejected"}


def _result_text(result: object) -> str:
    """Extract text from common MCP-backed LangChain tool results."""
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
    return json.dumps(result, default=str)


def _issues_from_result(result: object) -> list[dict]:
    """Parse the issue list returned by Linear MCP."""
    try:
        payload = json.loads(_result_text(result))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict) and isinstance(payload.get("issues"), list):
        return [issue for issue in payload["issues"] if isinstance(issue, dict)]
    return []


def _mapping_from_result(result: object) -> dict | None:
    """Parse the first JSON object from an MCP tool result."""
    try:
        payload = json.loads(_result_text(result))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _issue_from_payload(payload: object) -> dict | None:
    """Find an issue-shaped mapping in a Linear response payload."""
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("id"), str):
        return payload
    for key in ("issue", "data", "result"):
        issue = _issue_from_payload(payload.get(key))
        if issue is not None:
            return issue
    return None


async def _find_exact_issue(list_issues: BaseTool, title: str) -> dict | None:
    """Find an existing issue with the exact unique approved title."""
    result = await list_issues.ainvoke({"query": title})
    return next(
        (
            issue
            for issue in _issues_from_result(result)
            if issue.get("title", "").strip().casefold() == title.strip().casefold()
        ),
        None,
    )


def _creation_arguments(tool: BaseTool, draft: LinearIssueDraft) -> dict:
    """Map a validated draft onto the discovered create-tool schema."""
    args_schema = tool.args_schema
    if isinstance(args_schema, dict):
        schema = args_schema
    elif hasattr(args_schema, "model_json_schema"):
        schema = args_schema.model_json_schema()
    else:
        schema = {"properties": tool.args}

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    candidates = {
        "title": draft.title,
        "description": draft.approved_description(),
        "team": draft.team,
        "priority": draft.proposed_priority,
    }
    arguments = {key: value for key, value in candidates.items() if key in properties}
    missing = required - arguments.keys()
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"Approved draft cannot satisfy save_issue fields: {names}")
    if "title" not in arguments or "description" not in arguments:
        raise ValueError("save_issue must accept approved title and description")
    if "id" in arguments:
        raise ValueError("Issue creation must not include an update id")
    return arguments


def create_execute_node(tools: list[BaseTool]):
    """Create an async write node bound to runtime-discovered MCP tools."""
    list_issues = find_mcp_tool(tools, "list_issues") if tools else None
    save_issue = find_mcp_tool(tools, "save_issue") if tools else None

    async def execute_node(state: ApprovalState) -> dict:
        """Create the approved issue, reusing an exact duplicate on retries."""
        if state.get("approved") is not True:
            raise PermissionError("Linear issue creation requires explicit approval")
        if list_issues is None or save_issue is None:
            raise RuntimeError("Linear read and write MCP tools are unavailable")

        draft = LinearIssueDraft.model_validate(state["draft"])
        existing = await _find_exact_issue(list_issues, draft.title)
        if existing is not None:
            print("\n[ACTION] Matching Linear issue already exists; write skipped.")
            return {"created_issue": existing, "status": "duplicate_reused"}

        arguments = _creation_arguments(save_issue, draft)
        result = await save_issue.ainvoke(arguments)
        print("\n[ACTION] Approved Linear save_issue creation invoked.")
        return {
            "created_issue": {"create_result": _result_text(result)},
            "status": "created_pending_verification",
        }

    return execute_node


def create_verify_node(tools: list[BaseTool]):
    """Create a node that verifies the approved title exists in Linear."""
    list_issues = find_mcp_tool(tools, "list_issues") if tools else None
    try:
        get_issue = find_mcp_tool(tools, "get_issue") if tools else None
    except ValueError:
        get_issue = None

    async def verify_node(state: ApprovalState) -> dict:
        """Verify the remote result after creation or duplicate recovery."""
        if list_issues is None:
            raise RuntimeError("Linear list_issues tool is unavailable")

        draft = LinearIssueDraft.model_validate(state["draft"])
        create_result = state.get("created_issue", {}).get("create_result")
        created = _issue_from_payload(_mapping_from_result(create_result))
        if created is not None and get_issue is not None:
            result = await get_issue.ainvoke({"id": created["id"]})
            issue = _issue_from_payload(_mapping_from_result(result))
            if issue is not None:
                return {"created_issue": issue, "status": "created_verified"}

        issue = await _find_exact_issue(list_issues, draft.title)
        if issue is None:
            raise RuntimeError("Created Linear issue could not be verified")
        return {"created_issue": issue, "status": "created_verified"}

    return verify_node


def build_approval_graph(checkpointer, tools: list[BaseTool] | None = None):
    """Compile prepare, approval, guarded write, and verification stages."""
    tools = tools or []
    workflow = StateGraph(ApprovalState)
    workflow.add_node("prepare", prepare_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node(
        "execute",
        create_execute_node(tools),
        retry_policy=RetryPolicy(max_attempts=2),
    )
    workflow.add_node(
        "verify",
        create_verify_node(tools),
        retry_policy=RetryPolicy(max_attempts=2),
    )
    workflow.add_node("reject", reject_node)
    workflow.add_edge(START, "prepare")
    workflow.add_edge("prepare", "approval")
    workflow.add_conditional_edges(
        "approval",
        approval_router,
        {"execute": "execute", "reject": "reject"},
    )
    workflow.add_edge("execute", "verify")
    workflow.add_edge("verify", END)
    workflow.add_edge("reject", END)
    return workflow.compile(checkpointer=checkpointer)

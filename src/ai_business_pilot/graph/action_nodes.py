"""Human-approved Linear action nodes for the business-analysis graph."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from ai_business_pilot.approval import (
    approval_node,
    approval_router,
    create_execute_node,
    create_verify_node,
    reject_node,
)
from ai_business_pilot.graph.state import BusinessState
from ai_business_pilot.services.issue_drafting import draft_linear_issue


def route_draft(state: BusinessState) -> Literal["approval", "reporter"]:
    """Request approval only when drafting produced a proposed issue."""
    return "approval" if state.get("draft") else "reporter"


def create_action_nodes(
    model: BaseChatModel,
    action_tools: list[BaseTool],
) -> dict:
    """Bind drafting, approval, and isolated Linear write nodes."""

    async def issue_draft_node(state: BusinessState) -> dict:
        """Turn verified findings into a proposed issue or decline duplication."""
        print("\n[ACTION] Evaluating whether a new Linear issue is appropriate...")
        draft, reason = await draft_linear_issue(
            model,
            question=state["question"],
            analysis=state.get("analysis", ""),
            evidence=state.get("reporter_evidence") or state.get("evidence", ""),
        )
        if draft is None:
            print("[ACTION] No issue proposed.")
            return {
                "draft": None,
                "draft_reason": reason,
                "status": "issue_not_proposed",
            }
        print(f"[ACTION] Draft prepared: {draft.title}")
        return {
            "draft": draft.model_dump(),
            "draft_reason": reason,
            "status": "pending_approval",
        }

    return {
        "issue_draft": issue_draft_node,
        "approval": approval_node,
        "execute_action": create_execute_node(action_tools),
        "verify_action": create_verify_node(action_tools),
        "reject_action": reject_node,
        "approval_router": approval_router,
    }

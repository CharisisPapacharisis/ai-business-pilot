"""State, route, and runtime context types used by the analysis graph."""

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

Route = Literal["duckdb", "linear", "both"]
Action = Literal["none", "draft_issue"]


@dataclass(frozen=True)
class BusinessContext:
    """Identity used to isolate long-term memory between users."""

    user_id: str


class BusinessState(TypedDict):
    # Current question
    question: str

    # Planner decision
    route: NotRequired[Route]
    action: NotRequired[Action]
    plan: NotRequired[str]

    # Analyst results
    analysis: NotRequired[str]
    evidence: NotRequired[str]
    reporter_evidence: NotRequired[str]
    tool_calls: NotRequired[list[str]]

    # Final response
    final_answer: NotRequired[str]

    # Persistent conversation history
    history: NotRequired[list[str]]

    # Long-term memories retrieved for this user and run
    memories: NotRequired[list[str]]

    # Human-approved external action state
    draft: NotRequired[dict | None]
    draft_reason: NotRequired[str]
    approved: NotRequired[bool | None]
    status: NotRequired[str]
    created_issue: NotRequired[dict | None]
    action_outcomes: NotRequired[list[dict]]

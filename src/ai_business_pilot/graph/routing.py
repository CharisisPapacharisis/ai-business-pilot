"""Normalize model-selected routes and direct graph execution."""

import re
from typing import cast

from ai_business_pilot.graph.state import Action, BusinessState, Route

VALID_ROUTES = ("duckdb", "linear", "both")
VALID_ACTIONS = ("none", "draft_issue")


def explicit_action_intent(question: str) -> Action | None:
    """Recognize an explicit request to prepare a Linear issue draft."""
    normalized = " ".join(question.casefold().split())
    pattern = (
        r"\b(?:propose|draft|create|open|file|prepare)\b"
        r".{0,80}\b(?:linear\s+)?issue\b"
    )
    return "draft_issue" if re.search(pattern, normalized) else None


def normalize_route(content: object) -> Route:
    """Convert a model response into a supported route."""
    raw = str(content).strip().lower()
    route = raw.strip(" `\"'.")

    if route in VALID_ROUTES:
        return cast(Route, route)

    matches = set(re.findall(r"\b(?:duckdb|linear|both)\b", raw))
    if len(matches) == 1:
        return cast(Route, matches.pop())

    return "both"


def route_question(state: BusinessState) -> Route:
    """Return the validated analyst route stored in graph state."""

    route = state["route"]

    if route not in VALID_ROUTES:
        raise ValueError(f"Invalid route: {route}")

    print(f"\n[ROUTER] Selected: {route}")

    return route


def route_after_analysis(state: BusinessState) -> Action:
    """Send action requests to drafting and ordinary questions to reporting."""
    action = state.get("action", "none")
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action: {action}")
    return action

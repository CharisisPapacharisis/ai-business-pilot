"""Unit tests for route normalization and validation."""

import pytest

from ai_business_pilot.graph.routing import (
    explicit_action_intent,
    normalize_route,
    route_after_analysis,
    route_question,
)


@pytest.mark.parametrize(
    "question",
    [
        "Propose a Linear issue for post-launch monitoring.",
        "If none exists, draft a separate issue with the findings.",
        "Create an issue for the approved follow-up.",
    ],
)
def test_explicit_issue_request_is_detected(question: str) -> None:
    assert explicit_action_intent(question) == "draft_issue"


@pytest.mark.parametrize(
    "question",
    [
        "What is the status of this issue?",
        "Analyze gross profit and explain the findings.",
        "What does the proposed issue say?",
    ],
)
def test_non_action_question_is_not_overridden(question: str) -> None:
    assert explicit_action_intent(question) is None


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("duckdb", "duckdb"),
        (" `Linear` ", "linear"),
        ("The correct route is both.", "both"),
        ("Use DuckDB for this request.", "duckdb"),
    ],
)
def test_normalize_route_extracts_one_supported_route(
    response: object,
    expected: str,
) -> None:
    assert normalize_route(response) == expected


@pytest.mark.parametrize("response", ["unknown", "duckdb or linear", ""])
def test_normalize_route_falls_back_to_both(response: object) -> None:
    assert normalize_route(response) == "both"


def test_route_question_rejects_invalid_stored_route() -> None:
    with pytest.raises(ValueError, match="Invalid route"):
        route_question({"question": "test", "route": "invalid"})  # type: ignore[typeddict-item]


def test_action_routing_is_independent_from_source_route() -> None:
    state = {"question": "test", "route": "both"}
    assert route_after_analysis({**state, "action": "draft_issue"}) == "draft_issue"
    assert route_after_analysis({**state, "action": "none"}) == "none"

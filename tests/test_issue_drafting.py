"""Tests for converting analyst findings into guarded issue proposals."""

import asyncio

from ai_business_pilot.evidence import UNVERIFIED_EMPTY_RESULT
from ai_business_pilot.services.issue_drafting import (
    IssueDraftDecision,
    draft_linear_issue,
)


class StructuredModelStub:
    """Return one deterministic structured drafting decision."""

    def __init__(self, decision: IssueDraftDecision):
        self.decision = decision

    def with_structured_output(self, schema):
        assert schema is IssueDraftDecision
        return self

    async def ainvoke(self, messages):
        assert messages
        return self.decision


def test_existing_initiative_prevents_duplicate_draft() -> None:
    decision = IssueDraftDecision(
        should_create=False,
        reason="An existing Linear initiative already addresses the finding.",
        title="Existing initiative",
        description="No replacement issue should be created for this finding.",
        proposed_priority=3,
        supporting_evidence=[],
    )
    draft, reason = asyncio.run(
        draft_linear_issue(
            StructuredModelStub(decision),
            question="Find the least profitable product and propose an issue.",
            analysis="Linear initiative OPS-4 already covers the product.",
            evidence="Verified DuckDB and Linear evidence.",
        )
    )
    assert draft is None
    assert "existing" in reason.casefold()


def test_verified_findings_produce_validated_draft() -> None:
    decision = IssueDraftDecision(
        should_create=True,
        reason="No existing Linear initiative addresses the finding.",
        title="Review low-profit Headphones",
        description="Investigate options to improve Headphones gross profit.",
        proposed_priority=2,
        supporting_evidence=[
            "Headphones had the lowest verified gross profit.",
            "The Linear search found no equivalent initiative.",
        ],
    )
    draft, _ = asyncio.run(
        draft_linear_issue(
            StructuredModelStub(decision),
            question="Find the least profitable product and propose an issue.",
            analysis="Headphones ranked lowest and no initiative was found.",
            evidence="Verified DuckDB and Linear evidence.",
        )
    )
    assert draft is not None
    assert draft.title == "Review low-profit Headphones"
    assert draft.team == "Business Operations"
    assert len(draft.request_id) >= 8


def test_unverified_empty_result_blocks_issue_draft() -> None:
    draft, reason = asyncio.run(
        draft_linear_issue(
            object(),
            question="Propose an issue for a missing product.",
            analysis="The product may not exist.",
            evidence=f"{UNVERIFIED_EMPTY_RESULT}: verification still required",
        )
    )

    assert draft is None
    assert "not verified" in reason

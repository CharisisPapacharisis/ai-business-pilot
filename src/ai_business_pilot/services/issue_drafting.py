"""Build validated Linear issue drafts from verified analyst findings."""

from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ai_business_pilot.approval import LinearIssueDraft
from ai_business_pilot.evidence import UNVERIFIED_EMPTY_RESULT
from ai_business_pilot.fixture_config import LINEAR_DEFAULT_TEAM


class IssueDraftDecision(BaseModel):
    """Model decision about whether analysis warrants a new issue."""

    should_create: bool
    reason: str = Field(min_length=5)
    title: str = Field(min_length=5, max_length=255)
    description: str = Field(min_length=10)
    proposed_priority: int = Field(default=3, ge=0, le=4)
    supporting_evidence: list[str]


async def draft_linear_issue(
    model: BaseChatModel,
    *,
    question: str,
    analysis: str,
    evidence: str,
    team: str | None = None,
) -> tuple[LinearIssueDraft | None, str]:
    """Return a validated draft only when no equivalent initiative was found."""
    team = team or LINEAR_DEFAULT_TEAM
    if UNVERIFIED_EMPTY_RESULT in evidence:
        return (
            None,
            (
                "Issue drafting was skipped because an empty query result was not "
                "verified with a corrected lookup."
            ),
        )
    structured_model = model.with_structured_output(IssueDraftDecision)
    decision = await structured_model.ainvoke(
        [
            (
                "system",
                """You prepare proposed Linear issues from verified business analysis.

Decide first whether a new issue is appropriate. If the evidence shows an
existing relevant Linear initiative already addresses the finding, set
should_create to false. Never duplicate an existing initiative. Otherwise,
write a concise actionable title and description using only supplied facts.
Supporting evidence must contain the key verified figures and Linear-search
outcome. Do not invent IDs, metrics, owners, deadlines, or decisions.""",
            ),
            (
                "human",
                f"""User request:
{question}

Analyst findings:
{analysis}

Retrieved MCP evidence:
{evidence}

Target Linear team:
{team}""",
            ),
        ]
    )
    if not isinstance(decision, IssueDraftDecision):
        decision = IssueDraftDecision.model_validate(decision)
    if not decision.should_create:
        return None, decision.reason
    if not decision.supporting_evidence:
        raise ValueError("A proposed Linear issue requires supporting evidence")

    draft = LinearIssueDraft(
        request_id=str(uuid4()),
        title=decision.title,
        description=decision.description,
        team=team,
        proposed_priority=decision.proposed_priority,
        supporting_evidence=decision.supporting_evidence,
    )
    return draft, decision.reason

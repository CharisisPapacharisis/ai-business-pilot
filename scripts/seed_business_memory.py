"""Seed fictional long-term business preferences for local development."""

import asyncio
from pathlib import Path

from langgraph.store.sqlite.aio import AsyncSqliteStore

from ai_business_pilot.fixture_config import LINEAR_DEMO_ISSUE_TITLE
from ai_business_pilot.memory import save_business_memory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_DB = PROJECT_ROOT / "storage" / "business_memory.sqlite"
DEMO_USER_ID = "business-analyst-demo"

DEMO_MEMORIES = [
    (
        "pricing-demand-scenarios",
        "analysis_preference",
        "For pricing proposals, compare demand reductions of 0%, 5%, and 10%.",
    ),
    (
        "pricing-report-format",
        "reporting_preference",
        (
            "Show the baseline, proposed result, absolute difference, "
            "percentage difference, and assumptions."
        ),
    ),
    (
        "financial-display",
        "reporting_preference",
        "Present monetary values in USD rounded to two decimal places.",
    ),
    (
        "initiative-alias",
        "internal_terminology",
        f"Demo initiative means the {LINEAR_DEMO_ISSUE_TITLE} initiative.",
    ),
]


async def main() -> None:
    """Insert or update the local demonstration memories."""
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteStore.from_conn_string(str(MEMORY_DB)) as store:
        await store.setup()
        for key, category, content in DEMO_MEMORIES:
            await save_business_memory(
                store,
                user_id=DEMO_USER_ID,
                key=key,
                content=content,
                category=category,
                source="local development seed",
            )

    print(f"Seeded {len(DEMO_MEMORIES)} memories for {DEMO_USER_ID}.")
    print(f"Database: {MEMORY_DB}")


if __name__ == "__main__":
    asyncio.run(main())

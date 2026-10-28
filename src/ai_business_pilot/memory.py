"""Helpers for explicit, user-scoped long-term business memory."""

from datetime import UTC, datetime

from langgraph.store.base import BaseStore

MEMORY_ROOT = "business_memory"


def memory_namespace(user_id: str) -> tuple[str, str]:
    """Return the isolated store namespace for one user."""
    return (MEMORY_ROOT, user_id)


async def save_business_memory(
    store: BaseStore,
    *,
    user_id: str,
    key: str,
    content: str,
    category: str = "preference",
    source: str = "explicit",
) -> None:
    """Save or replace one explicitly approved business memory."""
    await store.aput(
        memory_namespace(user_id),
        key,
        {
            "category": category,
            "content": content,
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )

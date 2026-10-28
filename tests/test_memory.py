"""Unit tests for user-scoped long-term memory helpers."""

import asyncio

from langgraph.store.memory import InMemoryStore

from ai_business_pilot.memory import memory_namespace, save_business_memory


def test_memory_namespace_isolates_users() -> None:
    assert memory_namespace("alice") == ("business_memory", "alice")
    assert memory_namespace("alice") != memory_namespace("bob")


def test_save_business_memory_writes_structured_value() -> None:
    store = InMemoryStore()

    asyncio.run(
        save_business_memory(
            store,
            user_id="alice",
            key="report-format",
            content="Put the conclusion first.",
            category="reporting_preference",
            source="unit test",
        )
    )

    item = store.get(memory_namespace("alice"), "report-format")
    assert item is not None
    assert item.value["content"] == "Put the conclusion first."
    assert item.value["category"] == "reporting_preference"
    assert item.value["source"] == "unit test"
    assert "updated_at" in item.value
    assert store.get(memory_namespace("bob"), "report-format") is None

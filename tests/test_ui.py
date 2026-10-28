"""Tests for Streamlit-facing thread and checkpoint services."""

import tempfile
from pathlib import Path

import pytest

from ai_business_pilot.ui import runtime, threads

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace_tmp_path():
    """Create test storage inside the writable project workspace."""
    storage = PROJECT_ROOT / "storage"
    storage.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=storage) as folder:
        yield Path(folder)


def test_thread_catalog_persists_display_metadata(
    workspace_tmp_path,
    monkeypatch,
) -> None:
    catalog = workspace_tmp_path / "ui_threads.sqlite"
    monkeypatch.setattr(threads, "THREAD_CATALOG_DB", catalog)

    thread_id = threads.create_thread()
    threads.update_thread(thread_id, title="Lamp review", status="pending_approval")

    saved = threads.list_threads()
    assert saved == [
        {
            "thread_id": thread_id,
            "title": "Lamp review",
            "status": "pending_approval",
            "created_at": saved[0]["created_at"],
            "updated_at": saved[0]["updated_at"],
        }
    ]


def test_title_from_question_is_compact() -> None:
    assert threads.title_from_question("  Review   Lamp margin  ") == (
        "Review Lamp margin"
    )
    assert threads.title_from_question("x" * 60, limit=10) == "xxxxxxxxx…"


def test_empty_ui_thread_has_no_checkpoint_state(
    workspace_tmp_path,
    monkeypatch,
) -> None:
    checkpoint_db = workspace_tmp_path / "graph_checkpoints.sqlite"
    monkeypatch.setattr(runtime, "CHECKPOINT_DB", checkpoint_db)

    assert runtime.load_thread_state("ui-empty") == {}

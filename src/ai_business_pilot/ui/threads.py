"""Small SQLite catalog for displaying persistent conversation threads."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[3]
THREAD_CATALOG_DB = PROJECT_ROOT / "storage" / "ui_threads.sqlite"


def _connect() -> sqlite3.Connection:
    """Open and initialize the UI thread catalog."""
    THREAD_CATALOG_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(THREAD_CATALOG_DB)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_threads (
            thread_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Yield one catalog connection and always release its file handle."""
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def create_thread(title: str = "New conversation") -> str:
    """Create a catalog entry and return its graph thread ID."""
    thread_id = f"ui-{uuid4()}"
    now = datetime.now(UTC).isoformat()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO ui_threads(thread_id, title, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (thread_id, title, "idle", now, now),
        )
    return thread_id


def list_threads() -> list[dict]:
    """Return UI threads in most-recently-used order."""
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT thread_id, title, status, created_at, updated_at
            FROM ui_threads
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def update_thread(
    thread_id: str,
    *,
    title: str | None = None,
    status: str | None = None,
) -> None:
    """Update display metadata after a graph operation."""
    assignments = ["updated_at = ?"]
    values: list[str] = [datetime.now(UTC).isoformat()]
    if title is not None:
        assignments.append("title = ?")
        values.append(title)
    if status is not None:
        assignments.append("status = ?")
        values.append(status)
    values.append(thread_id)
    with _connection() as connection:
        connection.execute(
            f"UPDATE ui_threads SET {', '.join(assignments)} WHERE thread_id = ?",
            values,
        )


def title_from_question(question: str, limit: int = 48) -> str:
    """Build a compact sidebar title from the first user question."""
    compact = " ".join(question.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 1]}…"

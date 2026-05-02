"""SQLite persistence for chat threads and messages."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from uuid import uuid4

from project_paths import DB_DIR, ensure_runtime_dirs

ensure_runtime_dirs()

SESSIONS_DB = DB_DIR / "sessions.sqlite3"
_db_lock = threading.RLock()


def init_session_db() -> None:
    """Initialize tables and indexes for thread/message persistence."""
    with _db_lock:
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reasoning TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_thread_time
                ON messages(thread_id, timestamp, id);
                """
            )


def create_thread(title: str = "New Session", thread_id: str | None = None) -> dict:
    now = datetime.now().isoformat()
    tid = thread_id or f"thread_{uuid4().hex[:12]}"
    with _db_lock:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO threads(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (tid, title, now, now),
            )
    return get_thread(tid)


def ensure_thread_exists(thread_id: str, title: str = "New Session") -> dict:
    thread = get_thread(thread_id, raise_missing=False)
    if thread:
        touch_thread(thread_id)
        return get_thread(thread_id)
    return create_thread(title=title, thread_id=thread_id)


def touch_thread(thread_id: str) -> None:
    now = datetime.now().isoformat()
    with _db_lock:
        with _connect() as conn:
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))


def get_thread(thread_id: str, raise_missing: bool = True) -> dict | None:
    with _db_lock:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT t.id, t.title, t.created_at, t.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS message_count
                FROM threads t
                WHERE t.id = ?
                """,
                (thread_id,),
            ).fetchone()
    if row is None:
        if raise_missing:
            raise KeyError(f"Thread not found: {thread_id}")
        return None
    return dict(row)


def delete_messages_from(thread_id: str, from_message_id: int) -> bool:
    """Delete a message and all subsequent messages in a thread."""
    with _db_lock:
        with _connect() as conn:
            result = conn.execute(
                "DELETE FROM messages WHERE thread_id = ? AND id >= ?",
                (thread_id, from_message_id)
            )
            # Update thread updated_at timestamp
            if result.rowcount > 0:
                conn.execute(
                    "UPDATE threads SET updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), thread_id)
                )
    return result.rowcount > 0


def list_threads(limit: int = 50, offset: int = 0) -> list[dict]:
    with _db_lock:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.title, t.created_at, t.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS message_count
                FROM threads t
                ORDER BY datetime(t.updated_at) DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [dict(r) for r in rows]


def update_thread(thread_id: str, title: str | None = None, updated_at: str | None = None) -> dict:
    existing = get_thread(thread_id)
    new_title = title if title is not None else existing["title"]
    new_updated_at = updated_at or datetime.now().isoformat()
    with _db_lock:
        with _connect() as conn:
            conn.execute(
                "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
                (new_title, new_updated_at, thread_id),
            )
    return get_thread(thread_id)


def delete_thread(thread_id: str) -> bool:
    with _db_lock:
        with _connect() as conn:
            result = conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
    return result.rowcount > 0


def add_message(
    thread_id: str,
    role: str,
    content: str,
    reasoning: list[str] | None = None,
    timestamp: str | None = None,
) -> dict:
    ts = timestamp or datetime.now().isoformat()
    reasoning_json = json.dumps(reasoning or [], ensure_ascii=False)
    with _db_lock:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO messages(thread_id, role, content, reasoning, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, role, content, reasoning_json, ts),
            )
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (ts, thread_id))
    return {
        "thread_id": thread_id,
        "role": role,
        "content": content,
        "reasoning": reasoning or [],
        "timestamp": ts,
    }


def list_messages(thread_id: str) -> list[dict]:
    with _db_lock:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, reasoning, timestamp
                FROM messages
                WHERE thread_id = ?
                ORDER BY id ASC
                """,
                (thread_id,),
            ).fetchall()

    messages: list[dict] = []
    for row in rows:
        reasoning_value = []
        if row["reasoning"]:
            try:
                reasoning_value = json.loads(row["reasoning"])
            except json.JSONDecodeError:
                reasoning_value = []
        messages.append(
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "reasoning": reasoning_value,
                "timestamp": row["timestamp"],
            }
        )
    return messages


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SESSIONS_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
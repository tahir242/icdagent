"""Runtime utilities for capturing and streaming agent thinking."""

from __future__ import annotations

import json
import re
import threading
from contextvars import ContextVar, Token
from datetime import datetime
from pathlib import Path

from project_paths import THINKING_DIR, ensure_runtime_dirs

ensure_runtime_dirs()

_current_thread_id: ContextVar[str | None] = ContextVar("thinking_thread_id", default=None)
_current_run_id: ContextVar[str | None] = ContextVar("thinking_run_id", default=None)

_runs: dict[str, list[dict]] = {}
_run_thread_map: dict[str, str] = {}
_lock = threading.Lock()


def bind_run_context(thread_id: str, run_id: str) -> tuple[Token, Token]:
    """Bind thread/run context for the current execution thread."""
    with _lock:
        _runs[run_id] = []
        _run_thread_map[run_id] = thread_id
    t1 = _current_thread_id.set(thread_id)
    t2 = _current_run_id.set(run_id)
    _append_session_line(thread_id, f"\n=== Run {run_id} @ {datetime.now().isoformat()} ===\n")
    return t1, t2


def unbind_run_context(tokens: tuple[Token, Token]) -> None:
    """Reset thread/run context."""
    thread_token, run_token = tokens
    _current_thread_id.reset(thread_token)
    _current_run_id.reset(run_token)


def record_thought(thought: str) -> None:
    """Record a thinking step for streaming, persistence, and final response usage."""
    now = datetime.now().isoformat()
    normalized = _normalize_thought(thought)
    thread_id = _current_thread_id.get() or "unknown_thread"
    run_id = _current_run_id.get()
    entry = {"thought": normalized, "timestamp": now}

    if run_id:
        with _lock:
            if run_id not in _runs:
                _runs[run_id] = []
                _run_thread_map[run_id] = thread_id
            _runs[run_id].append(entry)

    _append_session_line(thread_id, _format_thought_log_entry(now, normalized))


def get_new_thoughts(run_id: str, cursor: int) -> tuple[list[dict], int]:
    """Return new thoughts for a run since cursor and updated cursor."""
    with _lock:
        items = _runs.get(run_id, [])
        if cursor >= len(items):
            return [], cursor
        new_items = items[cursor:]
        return new_items, len(items)


def get_all_thought_text(run_id: str) -> list[str]:
    """Return all thought text for a run."""
    with _lock:
        return [item["thought"] for item in _runs.get(run_id, [])]


def finalize_run(run_id: str, persist_json: bool = True) -> None:
    """Optionally persist a run snapshot and release in-memory state."""
    with _lock:
        thread_id = _run_thread_map.get(run_id)
        run_items = _runs.get(run_id, [])

    if persist_json and thread_id and run_items:
        payload = {"run_id": run_id, "thread_id": thread_id, "thoughts": run_items}
        _append_session_line(thread_id, json.dumps(payload, ensure_ascii=True) + "\n")

    with _lock:
        _runs.pop(run_id, None)
        _run_thread_map.pop(run_id, None)


def _append_session_line(thread_id: str, line: str) -> None:
    safe_thread = _sanitize_filename(thread_id)
    log_file = THINKING_DIR / f"{safe_thread}.txt"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line)


def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return cleaned or "unknown_thread"


def _normalize_thought(value: str) -> str:
    text = (value or "").replace("<|", "").replace("|>", "")
    text = re.sub(r'(?<!\s)\|(?!\s)', "", text)
    text = re.sub(r'[\|"]{2,}', " ", text)
    text = text.replace("<", "").replace(">", "")
    text = re.sub(r'\(Conf:\s*\d+%\)\s*', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    text = text.replace('""', '"').strip(" \"")
    return text


def _format_thought_log_entry(timestamp: str, thought: str) -> str:
    parts = [part.strip() for part in thought.split(" | ") if part.strip()]
    if not parts:
        return f"[{timestamp}] (empty thought)\n"
    header = parts[0]
    detail_lines = [f"  - {part}\n" for part in parts[1:]]
    return f"[{timestamp}] {header}\n" + "".join(detail_lines)

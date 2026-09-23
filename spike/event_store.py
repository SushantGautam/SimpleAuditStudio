"""Durable event store for the spike.

Stands in for the PostgreSQL ``AuditEvent`` table. In production, progress is
written to Postgres and streamed to browsers via SSE with Last-Event-ID replay.
Here we use a local SQLite file so the same durability semantics (append-only,
monotonic id, survives process restart) can be exercised without a live DB.

The key property under test: events written by a worker are durable and
re-readable after the worker process is killed and restarted.
"""
from __future__ import annotations

import os
import sqlite3
import threading

_LOCK = threading.Lock()


def _db_path() -> str:
    return os.environ.get("SPIKE_EVENT_DB", "spike/events.sqlite3")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the event/result tables if they do not exist."""
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                version_item_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scenario_result (
                run_id TEXT NOT NULL,
                version_item_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (run_id, version_item_id)
            )
            """
        )


def append_event(run_id: str, version_item_id: str, kind: str, payload: dict | None = None) -> int:
    """Append an event and return its monotonic id (used as SSE Last-Event-ID)."""
    import json

    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO audit_event (run_id, version_item_id, kind, payload) VALUES (?, ?, ?, ?)",
            (run_id, version_item_id, kind, json.dumps(payload or {})),
        )
        return int(cur.lastrowid)


def list_events(run_id: str, after_id: int = 0) -> list[dict]:
    """Return events for a run with id > after_id, ordered by id (SSE replay)."""
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT id, run_id, version_item_id, kind, payload FROM audit_event "
            "WHERE run_id = ? AND id > ? ORDER BY id ASC",
            (run_id, after_id),
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_result(run_id: str, version_item_id: str, status: str, attempts: int) -> None:
    """Idempotent final-result write keyed on (run_id, version_item_id).

    Re-executing the same scenario must not create a duplicate row; it may only
    update the existing one. This is the idempotency invariant under test.
    """
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO scenario_result (run_id, version_item_id, status, attempts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (run_id, version_item_id) DO UPDATE SET
                status = excluded.status,
                attempts = MAX(scenario_result.attempts, excluded.attempts)
            """,
            (run_id, version_item_id, status, attempts),
        )


def count_results(run_id: str) -> int:
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM scenario_result WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row["n"])


def get_result(run_id: str, version_item_id: str) -> dict | None:
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scenario_result WHERE run_id = ? AND version_item_id = ?",
            (run_id, version_item_id),
        ).fetchone()
        return dict(row) if row else None


def reset() -> None:
    """Wipe all spike state (test isolation)."""
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM audit_event")
        conn.execute("DELETE FROM scenario_result")

"""
Data layer for SimpleAudit Platform.

PostgreSQL in the reference architecture; SQLite here so the platform runs
portably with zero external services. The schema mirrors the spec's domain model:

    Scenario            1 - N  ScenarioRevision
    ScenarioSet         1 - N  ScenarioSetVersion
    ScenarioSetVersion  N - N  ScenarioRevision   (via ScenarioSetVersionItem)
    ModelEndpoint       (model registry)
    AuditRun            -> pins one ScenarioSetVersion + frozen config snapshots
    AuditRunScenario    per-scenario result rows
    Comparison          saved comparisons

Key invariant from the spec: an AuditRun points at an immutable
ScenarioSetVersion, never at a mutable ScenarioSet. Editing scenarios creates a
new version and never touches a version an audit already used.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "platform.db"

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS scenario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,           -- stable identity across revisions
    title TEXT NOT NULL,
    category TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_revision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL REFERENCES scenario(id),
    revision INTEGER NOT NULL,
    description TEXT,
    expected_behavior TEXT,             -- JSON list
    test_prompt TEXT,
    metadata TEXT,                      -- JSON object
    content_hash TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(scenario_id, revision)
);

CREATE TABLE IF NOT EXISTS scenario_set (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_set_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id INTEGER NOT NULL REFERENCES scenario_set(id),
    version INTEGER NOT NULL,
    scenario_count INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(set_id, version)
);

CREATE TABLE IF NOT EXISTS scenario_set_version_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES scenario_set_version(id),
    scenario_id INTEGER NOT NULL REFERENCES scenario(id),
    revision_id INTEGER NOT NULL REFERENCES scenario_revision(id),
    position INTEGER NOT NULL,
    UNIQUE(version_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS model_endpoint (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'openai',
    base_url TEXT NOT NULL,
    model_id TEXT NOT NULL,
    capabilities TEXT,                  -- JSON
    default_parameters TEXT,            -- JSON
    secret_reference TEXT,              -- name of env var holding the key
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_by TEXT,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued|running|completed|failed|cancelled
    queued_at TEXT,
    started_at TEXT,
    finished_at TEXT,

    scenario_set_version_id INTEGER NOT NULL REFERENCES scenario_set_version(id),

    target_config_snapshot TEXT NOT NULL,     -- JSON
    auditor_config_snapshot TEXT NOT NULL,    -- JSON
    judge_config_snapshot TEXT NOT NULL,      -- JSON

    simpleaudit_version TEXT,
    git_commit TEXT,

    total_scenarios INTEGER NOT NULL DEFAULT 0,
    completed_scenarios INTEGER NOT NULL DEFAULT 0,
    failed_scenarios INTEGER NOT NULL DEFAULT 0,

    progress TEXT,                          -- JSON {stage, completed, total, successful, failed}
    current_stage TEXT,

    worker_job_id TEXT,                     -- queue job id (Hatchet run_id equivalent)
    summary_metrics TEXT,                   -- JSON
    artifact_uri TEXT,                      -- path/uri to full results JSON
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_run_scenario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES audit_run(id),
    scenario_id INTEGER REFERENCES scenario(id),
    scenario_name TEXT NOT NULL,
    severity TEXT,
    issues_found TEXT,                      -- JSON list
    positive_behaviors TEXT,                -- JSON list
    summary TEXT,
    recommendations TEXT,                   -- JSON list
    conversation TEXT,                      -- JSON list
    judgment TEXT,                          -- JSON
    target_tokens INTEGER NOT NULL DEFAULT 0,
    auditor_tokens INTEGER NOT NULL DEFAULT 0,
    judge_tokens INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'  -- pending|done|error
);

CREATE TABLE IF NOT EXISTS comparison (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    run_ids TEXT NOT NULL,                  -- JSON list
    only_identical_scenarios INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rev_scenario ON scenario_revision(scenario_id);
CREATE INDEX IF NOT EXISTS idx_ssv_set ON scenario_set_version(set_id);
CREATE INDEX IF NOT EXISTS idx_ssvi_version ON scenario_set_version_item(version_id);
CREATE INDEX IF NOT EXISTS idx_run_status ON audit_run(status);
CREATE INDEX IF NOT EXISTS idx_ars_run ON audit_run_scenario(run_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def q(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def q1(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    rows = q(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or 0


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(s: Optional[str], default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return default

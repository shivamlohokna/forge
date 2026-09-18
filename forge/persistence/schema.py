"""Database schema definitions for Forge V2 persistence layer.

This module is the single source of truth for the SQLite DDL.
No Python-level business logic lives here — only table definitions,
index declarations, and schema version management.

Schema hierarchy (mirrors the result model exactly):

    workflow_runs           ← one row per Engine.run() call
        └── task_runs       ← one row per task within a workflow run
              └── task_attempts ← one row per individual retry attempt

Design decisions:
- All timestamps are stored as ISO-8601 strings in UTC (TEXT).
- JSON blobs (parameters, metadata, output) are stored as TEXT.
- NULLable columns are used where data may legitimately be absent
  (e.g. end_time before a run finishes, error fields on success).
- A schema_version table allows future migrations to be applied
  without dropping and recreating the database.
- All primary keys are TEXT (UUIDs/slugs from the domain models).
- Foreign key constraints are enforced (requires PRAGMA foreign_keys=ON).
"""

from __future__ import annotations

import sqlite3

# ── Schema version ────────────────────────────────────────────────────────────
# Increment this integer whenever the DDL changes in a backwards-incompatible
# way.  Migration logic keyed on this number goes in store.py.
SCHEMA_VERSION: int = 3

# ── DDL statements ────────────────────────────────────────────────────────────

_DDL_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER NOT NULL,
    applied_at      TEXT    NOT NULL   -- ISO-8601 UTC
);
"""

_DDL_WORKFLOW_RUNS = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    -- Identity
    run_id          TEXT    PRIMARY KEY,   -- Unique execution instance ID
    workflow_id     TEXT    NOT NULL,      -- Workflow definition ID
    workflow_name   TEXT    NOT NULL,

    -- Status
    status          TEXT    NOT NULL,      -- WorkflowStatus value

    -- Timing (ISO-8601 UTC strings)
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,                  -- NULL until the run completes

    -- Duration in fractional seconds
    duration_seconds REAL,

    -- JSON-serialised dicts (may be '{}' but never NULL)
    parameters      TEXT    NOT NULL DEFAULT '{}',
    metadata        TEXT    NOT NULL DEFAULT '{}',

    -- Aggregate counters (denormalised for fast list queries)
    total_tasks     INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failed_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count   INTEGER NOT NULL DEFAULT 0,
    blocked_count   INTEGER NOT NULL DEFAULT 0,
    cancelled_count INTEGER NOT NULL DEFAULT 0,

    -- Orphan recovery: OS process ID of the writing Forge process (v3)
    worker_pid      INTEGER
);
"""

_DDL_WORKFLOW_RUNS_IDX = """
CREATE INDEX IF NOT EXISTS idx_workflow_runs_name
    ON workflow_runs (workflow_name);
"""

_DDL_WORKFLOW_RUNS_WFID_IDX = """
CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id
    ON workflow_runs (workflow_id);
"""

_DDL_WORKFLOW_RUNS_STATUS_IDX = """
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status
    ON workflow_runs (status);
"""


_DDL_TASK_RUNS = """
CREATE TABLE IF NOT EXISTS task_runs (
    -- Identity
    task_run_id     TEXT    PRIMARY KEY,   -- TaskResult.task_id
    run_id          TEXT    NOT NULL
                            REFERENCES workflow_runs(run_id)
                            ON DELETE CASCADE,
    task_name       TEXT    NOT NULL,

    -- Status
    status          TEXT    NOT NULL,      -- TaskStatus value

    -- Timing
    started_at      TEXT,
    finished_at     TEXT,
    duration_seconds REAL,

    -- Aggregate
    attempt_count   INTEGER NOT NULL DEFAULT 0,

    -- Final outcome (from last attempt)
    output          TEXT,                  -- JSON or NULL
    error_message   TEXT,
    error_traceback TEXT
);
"""

_DDL_TASK_RUNS_IDX = """
CREATE INDEX IF NOT EXISTS idx_task_runs_run_id
    ON task_runs (run_id);
"""

_DDL_TASK_RUNS_NAME_IDX = """
CREATE INDEX IF NOT EXISTS idx_task_runs_task_name
    ON task_runs (task_name);
"""

_DDL_TASK_ATTEMPTS = """
CREATE TABLE IF NOT EXISTS task_attempts (
    -- Surrogate primary key (auto-assigned by SQLite)
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Foreign key back to the owning task run
    task_run_id     TEXT    NOT NULL
                            REFERENCES task_runs(task_run_id)
                            ON DELETE CASCADE,

    -- Attempt metadata
    attempt_number  INTEGER NOT NULL,
    status          TEXT    NOT NULL,      -- TaskStatus value

    -- Timing
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    duration_seconds REAL,

    -- Outcome
    output          TEXT,                  -- JSON or NULL
    error_message   TEXT,
    error_traceback TEXT
);
"""

_DDL_TASK_ATTEMPTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_task_attempts_task_run_id
    ON task_attempts (task_run_id);
"""

# ── Public interface ──────────────────────────────────────────────────────────

# All DDL statements in the order they must be executed.
ALL_DDL: list[str] = [
    _DDL_SCHEMA_VERSION,
    _DDL_WORKFLOW_RUNS,
    _DDL_WORKFLOW_RUNS_IDX,
    _DDL_WORKFLOW_RUNS_WFID_IDX,
    _DDL_WORKFLOW_RUNS_STATUS_IDX,
    _DDL_TASK_RUNS,
    _DDL_TASK_RUNS_IDX,
    _DDL_TASK_RUNS_NAME_IDX,
    _DDL_TASK_ATTEMPTS,
    _DDL_TASK_ATTEMPTS_IDX,
]


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply the full schema DDL to the given connection.

    Safe to call on an existing database — all statements use
    ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``.

    Enables foreign key enforcement and WAL journal mode for
    improved concurrent read performance.

    Args:
        conn: An open :class:`sqlite3.Connection`.
    """
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    # Allow concurrent CLI commands to wait up to 5 s before failing with
    # "database is locked" instead of immediately raising an error.
    conn.execute("PRAGMA busy_timeout = 5000;")

    with conn:
        # 1. Ensure core tables exist
        conn.execute(_DDL_SCHEMA_VERSION)
        conn.execute(_DDL_WORKFLOW_RUNS)

        # 2. Migration: Check if existing workflow_runs is missing workflow_id column (v1 -> v2)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(workflow_runs);").fetchall()
        ]
        if "workflow_id" not in columns:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN workflow_id TEXT NOT NULL DEFAULT '';")
            conn.execute("UPDATE workflow_runs SET workflow_id = run_id WHERE workflow_id = '';")

        # 3. Migration: Add worker_pid column if missing (v2 -> v3)
        if "worker_pid" not in columns:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN worker_pid INTEGER;")

        # 3. Apply all DDL statements (indexes, remaining tables)
        for statement in ALL_DDL:
            conn.execute(statement)

        # 4. Record or update schema version
        from datetime import datetime, timezone
        row = conn.execute("SELECT version FROM schema_version LIMIT 1;").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )
        elif row[0] < SCHEMA_VERSION:
            conn.execute(
                "UPDATE schema_version SET version = ?, applied_at = ?;",
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )




def get_schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the recorded schema version, or None if not yet set.

    Args:
        conn: An open :class:`sqlite3.Connection`.

    Returns:
        The stored version integer, or ``None`` for a blank database.
    """
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1;").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None

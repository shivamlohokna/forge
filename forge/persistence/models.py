"""Persistence models for Forge V2 — Python ↔ SQLite row mapping.

This module defines lightweight dataclasses that map directly onto the
three database tables introduced in schema.py.  They are *not* the same
objects as the runtime result models (WorkflowResult / TaskResult /
TaskAttempt); instead they are thin, serialisation-oriented views whose
sole job is to carry data across the repository boundary.

Conversion helpers on each model handle:
  - datetime ↔ ISO-8601 TEXT
  - dict/Any ↔ JSON TEXT
  - Enum ↔ string value

Nothing in this module imports from forge.core so that the persistence
layer never gains a circular dependency on the execution kernel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _to_iso(dt: datetime | None) -> str | None:
    """Serialise a datetime to ISO-8601, or return None."""
    return dt.isoformat() if dt is not None else None


def _from_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string back to a timezone-aware datetime."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _to_json(obj: Any) -> str:
    """Serialise an arbitrary Python object to a JSON string.

    Falls back to ``str(obj)`` if the object is not directly
    JSON-serialisable (e.g. bytes, custom classes).
    """
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(obj))


def _from_json(text: str | None) -> Any:
    """Deserialise a JSON string, returning None for missing values."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


# ── Persistence models ────────────────────────────────────────────────────────

@dataclass
class WorkflowRunRecord:
    """Row model for the ``workflow_runs`` table.

    Maps 1:1 to a single Engine.run() execution.
    """

    run_id: str
    workflow_name: str
    status: str                        # WorkflowStatus.value
    workflow_id: str = ""              # Workflow definition ID (defaults to run_id)

    started_at: str = ""               # ISO-8601 UTC
    finished_at: str | None = None
    duration_seconds: float | None = None

    parameters: str = "{}"            # JSON
    metadata: str = "{}"              # JSON

    # Denormalised counters (updated on complete_workflow_run)
    total_tasks: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    blocked_count: int = 0
    cancelled_count: int = 0

    # Orphan-recovery: OS PID of the writing process (v3 schema; None for
    # legacy rows created before this column was added).
    worker_pid: int | None = None

    def __post_init__(self) -> None:
        if not self.workflow_id:
            self.workflow_id = self.run_id

    # ── Serialisation helpers ─────────────────────────────────────────────────

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> WorkflowRunRecord:
        """Construct a record from a raw sqlite3 row tuple.

        Supports v1 (14 columns), v2 (15 columns), and v3 (16 columns with
        worker_pid) row layouts, allowing graceful reads from migrated DBs.
        """
        worker_pid: int | None = None
        if len(row) >= 16:
            (
                run_id, workflow_id, workflow_name, status,
                started_at, finished_at, duration_seconds,
                parameters, metadata,
                total_tasks, success_count, failed_count,
                skipped_count, blocked_count, cancelled_count,
                worker_pid,
            ) = row[:16]
        elif len(row) >= 15:
            (
                run_id, workflow_id, workflow_name, status,
                started_at, finished_at, duration_seconds,
                parameters, metadata,
                total_tasks, success_count, failed_count,
                skipped_count, blocked_count, cancelled_count,
            ) = row[:15]
        else:
            (
                run_id, workflow_name, status,
                started_at, finished_at, duration_seconds,
                parameters, metadata,
                total_tasks, success_count, failed_count,
                skipped_count, blocked_count, cancelled_count,
            ) = row[:14]
            workflow_id = run_id

        return cls(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            parameters=parameters or "{}",
            metadata=metadata or "{}",
            total_tasks=total_tasks or 0,
            success_count=success_count or 0,
            failed_count=failed_count or 0,
            skipped_count=skipped_count or 0,
            blocked_count=blocked_count or 0,
            cancelled_count=cancelled_count or 0,
            worker_pid=worker_pid,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a human-readable dictionary with deserialised fields."""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "parameters": _from_json(self.parameters),
            "metadata": _from_json(self.metadata),
            "total_tasks": self.total_tasks,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "blocked_count": self.blocked_count,
            "cancelled_count": self.cancelled_count,
            "worker_pid": self.worker_pid,
        }



@dataclass
class TaskRunRecord:
    """Row model for the ``task_runs`` table.

    Maps 1:1 to a single TaskResult within a workflow run.
    """

    task_run_id: str                   # TaskResult.task_id
    run_id: str                        # FK → workflow_runs.run_id
    task_name: str
    status: str                        # TaskStatus.value

    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None

    attempt_count: int = 0

    output: str | None = None          # JSON or None
    error_message: str | None = None
    error_traceback: str | None = None

    # ── Serialisation helpers ─────────────────────────────────────────────────

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> TaskRunRecord:
        """Construct a record from a raw sqlite3 row tuple."""
        (
            task_run_id, run_id, task_name, status,
            started_at, finished_at, duration_seconds,
            attempt_count,
            output, error_message, error_traceback,
        ) = row
        return cls(
            task_run_id=task_run_id,
            run_id=run_id,
            task_name=task_name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            attempt_count=attempt_count or 0,
            output=output,
            error_message=error_message,
            error_traceback=error_traceback,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a human-readable dictionary with deserialised fields."""
        return {
            "task_run_id": self.task_run_id,
            "run_id": self.run_id,
            "task_name": self.task_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "attempt_count": self.attempt_count,
            "output": _from_json(self.output),
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
        }


@dataclass
class TaskAttemptRecord:
    """Row model for the ``task_attempts`` table.

    Maps 1:1 to a single TaskAttempt (one retry attempt).
    """

    task_run_id: str                   # FK → task_runs.task_run_id
    attempt_number: int
    status: str                        # TaskStatus.value

    started_at: str                    # ISO-8601 UTC
    finished_at: str | None = None
    duration_seconds: float | None = None

    output: str | None = None          # JSON or None
    error_message: str | None = None
    error_traceback: str | None = None

    # Auto-assigned by SQLite — None before INSERT
    id: int | None = None

    # ── Serialisation helpers ─────────────────────────────────────────────────

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> TaskAttemptRecord:
        """Construct a record from a raw sqlite3 row tuple."""
        (
            row_id, task_run_id, attempt_number, status,
            started_at, finished_at, duration_seconds,
            output, error_message, error_traceback,
        ) = row
        return cls(
            id=row_id,
            task_run_id=task_run_id,
            attempt_number=attempt_number,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            output=output,
            error_message=error_message,
            error_traceback=error_traceback,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a human-readable dictionary with deserialised fields."""
        return {
            "id": self.id,
            "task_run_id": self.task_run_id,
            "attempt_number": self.attempt_number,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "output": _from_json(self.output),
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
        }


# ── Module-level convenience re-exports ──────────────────────────────────────

__all__ = [
    "WorkflowRunRecord",
    "TaskRunRecord",
    "TaskAttemptRecord",
    # Helpers exposed for use in store.py
    "_now_iso",
    "_to_iso",
    "_from_iso",
    "_to_json",
    "_from_json",
]

"""ExecutionStore — the repository boundary for Forge V2 persistence.

This module is the only place in the codebase that speaks SQL.

Everything above (Engine, WorkflowResult, TaskResult) talks to
ExecutionStore through a clean Python API. Everything below (SQLite) is an
implementation detail hidden behind that API.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from forge.utils.pid import is_process_alive
from forge.utils.sanitizer import sanitize as _sanitize_output

from .models import (
    TaskAttemptRecord,
    TaskRunRecord,
    WorkflowRunRecord,
    _from_json,
    _now_iso,
    _to_iso,
    _to_json,
)
from .schema import init_schema

logger = logging.getLogger("forge.persistence")


class ExecutionStore:
    """Repository for persisting and querying Forge workflow execution history.

    Wraps SQLite via the stdlib ``sqlite3`` module.

    Thread-safe: one SQLite connection is guarded by a reentrant lock so
    multiple Engine worker threads can safely call persistence methods.

    Use the factory classmethods rather than instantiating directly::

        store = ExecutionStore.create("forge_runs.db")
        store = ExecutionStore.in_memory()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        init_schema(self._conn)

    # ── Factory classmethods ────────────────────────────────────────────────

    @classmethod
    def create(cls, path: str | Path) -> ExecutionStore:
        """Create a file-backed ExecutionStore."""
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )

        logger.debug("Opened Forge database at %s", db_path)
        return cls(conn)

    @classmethod
    def in_memory(cls) -> ExecutionStore:
        """Create an ephemeral in-memory ExecutionStore."""
        conn = sqlite3.connect(
            ":memory:",
            check_same_thread=False,
        )
        return cls(conn)

    # ── Context manager ─────────────────────────────────────────────────────

    def __enter__(self) -> ExecutionStore:
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    # ── Internal helpers ────────────────────────────────────────────────────

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Yield a cursor inside a serialized, auto-committed transaction."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # ── Write API ────────────────────────────────────────────────────────────

    def create_workflow_run(
        self,
        run_id: str,
        workflow_name: str,
        status: str,
        workflow_id: str | None = None,
        started_at: str | None = None,
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowRunRecord:
        """Insert a new workflow run row when execution begins."""
        resolved_workflow_id = (
            workflow_id if workflow_id is not None else run_id
        )
        worker_pid = os.getpid()

        record = WorkflowRunRecord(
            run_id=run_id,
            workflow_id=resolved_workflow_id,
            workflow_name=workflow_name,
            status=status,
            started_at=started_at or _now_iso(),
            parameters=_to_json(parameters or {}),
            metadata=_to_json(metadata or {}),
            worker_pid=worker_pid,
        )

        with self._transaction() as cur:
            cur.execute(
                """
                INSERT INTO workflow_runs (
                    run_id,
                    workflow_id,
                    workflow_name,
                    status,
                    started_at,
                    parameters,
                    metadata,
                    worker_pid
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.workflow_id,
                    record.workflow_name,
                    record.status,
                    record.started_at,
                    record.parameters,
                    record.metadata,
                    record.worker_pid,
                ),
            )

        logger.debug(
            "Created workflow run %s (workflow_id=%s, pid=%d)",
            run_id,
            record.workflow_id,
            worker_pid,
        )
        return record

    def save_task_run(
        self,
        run_id: str,
        task_run_id: str,
        task_name: str,
        status: str,
        started_at: str | None,
        finished_at: str | None,
        duration_seconds: float | None,
        attempt_count: int,
        output: Any,
        error_message: str | None,
        error_traceback: str | None,
    ) -> TaskRunRecord:
        """Insert or replace a task run row.

        Task output is sanitized only at the persistence boundary so tasks
        still receive real values during execution.
        """
        sanitized_output = (
            _sanitize_output(output)
            if output is not None
            else None
        )

        record = TaskRunRecord(
            task_run_id=task_run_id,
            run_id=run_id,
            task_name=task_name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            attempt_count=attempt_count,
            output=(
                _to_json(sanitized_output)
                if sanitized_output is not None
                else None
            ),
            error_message=error_message,
            error_traceback=error_traceback,
        )

        with self._transaction() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO task_runs (
                    task_run_id,
                    run_id,
                    task_name,
                    status,
                    started_at,
                    finished_at,
                    duration_seconds,
                    attempt_count,
                    output,
                    error_message,
                    error_traceback
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_run_id,
                    record.run_id,
                    record.task_name,
                    record.status,
                    record.started_at,
                    record.finished_at,
                    record.duration_seconds,
                    record.attempt_count,
                    record.output,
                    record.error_message,
                    record.error_traceback,
                ),
            )

        logger.debug(
            "Saved task run %s (%s)",
            task_run_id,
            status,
        )
        return record

    def save_task_attempt(
        self,
        task_run_id: str,
        attempt_number: int,
        status: str,
        started_at: str,
        finished_at: str | None,
        duration_seconds: float | None,
        output: Any,
        error_message: str | None,
        error_traceback: str | None,
    ) -> TaskAttemptRecord:
        """Insert a task attempt row."""
        record = TaskAttemptRecord(
            task_run_id=task_run_id,
            attempt_number=attempt_number,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            output=(
                _to_json(output)
                if output is not None
                else None
            ),
            error_message=error_message,
            error_traceback=error_traceback,
        )

        with self._transaction() as cur:
            cur.execute(
                """
                INSERT INTO task_attempts (
                    task_run_id,
                    attempt_number,
                    status,
                    started_at,
                    finished_at,
                    duration_seconds,
                    output,
                    error_message,
                    error_traceback
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_run_id,
                    record.attempt_number,
                    record.status,
                    record.started_at,
                    record.finished_at,
                    record.duration_seconds,
                    record.output,
                    record.error_message,
                    record.error_traceback,
                ),
            )
            record.id = cur.lastrowid

        logger.debug(
            "Saved attempt #%d for task run %s (%s)",
            attempt_number,
            task_run_id,
            status,
        )
        return record

    def complete_workflow_run(
        self,
        run_id: str,
        status: str,
        finished_at: str | None,
        duration_seconds: float | None,
        total_tasks: int,
        success_count: int,
        failed_count: int,
        skipped_count: int,
        blocked_count: int,
        cancelled_count: int,
    ) -> None:
        """Update a workflow run row once execution finishes."""
        with self._transaction() as cur:
            cur.execute(
                """
                UPDATE workflow_runs SET
                    status = ?,
                    finished_at = ?,
                    duration_seconds = ?,
                    total_tasks = ?,
                    success_count = ?,
                    failed_count = ?,
                    skipped_count = ?,
                    blocked_count = ?,
                    cancelled_count = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    finished_at,
                    duration_seconds,
                    total_tasks,
                    success_count,
                    failed_count,
                    skipped_count,
                    blocked_count,
                    cancelled_count,
                    run_id,
                ),
            )

        logger.debug(
            "Completed workflow run %s → %s",
            run_id,
            status,
        )

    # ── Orphan-run recovery ─────────────────────────────────────────────────

    def recover_interrupted_runs(self) -> list[str]:
        """Mark orphaned RUNNING workflow runs as FAILED.

        A row is recovered only when:
        - its status is RUNNING, and
        - its worker_pid is known to be dead.

        Legacy rows with NULL worker_pid are left untouched because their
        owner cannot be determined safely.

        Process liveness is checked by ``forge.utils.pid.is_process_alive``:
        Windows uses the Win32 process API and POSIX uses signal 0.

        This method is explicitly opt-in and should be called by the CLI
        ``run`` command. It must not run automatically when opening the DB,
        because another Forge process may legitimately have RUNNING rows.
        """
        recovered: list[str] = []
        finished_at = _now_iso()

        # Snapshot candidate RUNNING rows in a short transaction.
        with self._transaction() as cur:
            rows = cur.execute(
                """
                SELECT run_id, worker_pid
                FROM workflow_runs
                WHERE status = 'RUNNING'
                """
            ).fetchall()

        for run_id, pid in rows:
            if pid is None:
                logger.debug(
                    "Skipping RUNNING run %s: no worker_pid recorded",
                    run_id,
                )
                continue

            try:
                is_alive = is_process_alive(pid)
            except Exception as exc:
                # Ambiguous process state must never cause recovery.
                logger.warning(
                    "Unexpected error checking pid %d for run %s: %s",
                    pid,
                    run_id,
                    exc,
                )
                continue

            if is_alive:
                continue

            # The status predicate prevents us from overwriting a run that
            # completed between the initial SELECT and this UPDATE.
            with self._transaction() as cur:
                cur.execute(
                    """
                    UPDATE workflow_runs
                    SET
                        status = 'FAILED',
                        finished_at = ?,
                        metadata = json_patch(
                            COALESCE(metadata, '{}'),
                            json_object(
                                'recovery_reason',
                                'process ' || ? || ' no longer exists'
                            )
                        )
                    WHERE run_id = ?
                      AND status = 'RUNNING'
                    """,
                    (finished_at, pid, run_id),
                )

                if cur.rowcount == 1:
                    recovered.append(run_id)
                    logger.info(
                        "Recovered orphaned run %s (worker_pid=%d was dead)",
                        run_id,
                        pid,
                    )

        if recovered:
            logger.info(
                "Orphan recovery complete: %d run(s) recovered: %s",
                len(recovered),
                recovered,
            )

        return recovered

    # ── Read API ─────────────────────────────────────────────────────────────

    _WORKFLOW_RUN_COLUMNS = """
        run_id,
        workflow_id,
        workflow_name,
        status,
        started_at,
        finished_at,
        duration_seconds,
        parameters,
        metadata,
        total_tasks,
        success_count,
        failed_count,
        skipped_count,
        blocked_count,
        cancelled_count,
        worker_pid
    """

    _TASK_RUN_COLUMNS = """
        task_run_id,
        run_id,
        task_name,
        status,
        started_at,
        finished_at,
        duration_seconds,
        attempt_count,
        output,
        error_message,
        error_traceback
    """

    _TASK_ATTEMPT_COLUMNS = """
        id,
        task_run_id,
        attempt_number,
        status,
        started_at,
        finished_at,
        duration_seconds,
        output,
        error_message,
        error_traceback
    """

    def get_workflow_run(
        self,
        run_id: str,
    ) -> WorkflowRunRecord | None:
        """Retrieve a workflow run by run_id.

        If no exact run_id match exists, run_id is also checked as a
        workflow_id and the most recent execution is returned.
        """
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT {self._WORKFLOW_RUN_COLUMNS}
                FROM workflow_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

            if row is None:
                row = self._conn.execute(
                    f"""
                    SELECT {self._WORKFLOW_RUN_COLUMNS}
                    FROM workflow_runs
                    WHERE workflow_id = ? OR workflow_name = ?
                    ORDER BY started_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (run_id, run_id),
                ).fetchone()

        return WorkflowRunRecord.from_row(row) if row else None

    def list_workflow_runs(
        self,
        workflow_name: str | None = None,
        workflow_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkflowRunRecord]:
        """List workflow runs with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []

        if workflow_name is not None:
            clauses.append("workflow_name = ?")
            params.append(workflow_name)

        if workflow_id is not None:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)

        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = (
            f"WHERE {' AND '.join(clauses)}"
            if clauses
            else ""
        )
        params.extend([limit, offset])

        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {self._WORKFLOW_RUN_COLUMNS}
                FROM workflow_runs
                {where}
                ORDER BY started_at DESC, rowid DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()

        return [
            WorkflowRunRecord.from_row(row)
            for row in rows
        ]

    def get_task_runs(
        self,
        run_id: str,
    ) -> list[TaskRunRecord]:
        """Return all task runs belonging to a workflow run."""
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {self._TASK_RUN_COLUMNS}
                FROM task_runs
                WHERE run_id = ?
                ORDER BY rowid ASC
                """,
                (run_id,),
            ).fetchall()

            if not rows:
                latest_run = self._conn.execute(
                    """
                    SELECT run_id
                    FROM workflow_runs
                    WHERE workflow_id = ?
                    ORDER BY started_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()

                if latest_run:
                    rows = self._conn.execute(
                        f"""
                        SELECT {self._TASK_RUN_COLUMNS}
                        FROM task_runs
                        WHERE run_id = ?
                        ORDER BY rowid ASC
                        """,
                        (latest_run[0],),
                    ).fetchall()

        return [
            TaskRunRecord.from_row(row)
            for row in rows
        ]

    def get_task_run(
        self,
        task_run_id: str,
    ) -> TaskRunRecord | None:
        """Retrieve a single task run by task_run_id."""
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT {self._TASK_RUN_COLUMNS}
                FROM task_runs
                WHERE task_run_id = ?
                """,
                (task_run_id,),
            ).fetchone()

            if row is None:
                row = self._conn.execute(
                    f"""
                    SELECT {self._TASK_RUN_COLUMNS}
                    FROM task_runs
                    WHERE task_run_id LIKE ?
                    ORDER BY rowid DESC
                    LIMIT 1
                    """,
                    (f"%:{task_run_id}",),
                ).fetchone()

        return TaskRunRecord.from_row(row) if row else None

    def get_task_attempts(
        self,
        task_run_id: str,
    ) -> list[TaskAttemptRecord]:
        """Return all attempts for a task run in attempt order."""
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {self._TASK_ATTEMPT_COLUMNS}
                FROM task_attempts
                WHERE task_run_id = ?
                ORDER BY attempt_number ASC
                """,
                (task_run_id,),
            ).fetchall()

            if not rows:
                rows = self._conn.execute(
                    f"""
                    SELECT {self._TASK_ATTEMPT_COLUMNS}
                    FROM task_attempts
                    WHERE task_run_id LIKE ?
                    ORDER BY attempt_number ASC
                    """,
                    (f"%:{task_run_id}",),
                ).fetchall()

        return [
            TaskAttemptRecord.from_row(row)
            for row in rows
        ]

    def count_workflow_runs(
        self,
        workflow_name: str | None = None,
    ) -> int:
        """Return the number of stored workflow runs."""
        with self._lock:
            if workflow_name is not None:
                row = self._conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM workflow_runs
                    WHERE workflow_name = ?
                    """,
                    (workflow_name,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM workflow_runs"
                ).fetchone()

        return row[0] if row else 0

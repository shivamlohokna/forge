"""Tests for Forge V2 persistence layer — Phase 5.

Coverage:
    5.1  Schema — table creation, idempotency, schema_version recording
    5.2  Models — row round-trip for all three record types
    5.3  Store  — full write/read API via in-memory store
         • create_workflow_run / complete_workflow_run
         • save_task_run / get_task_run / get_task_runs
         • save_task_attempt / get_task_attempts
         • list_workflow_runs (with filters)
         • count_workflow_runs
         • file-backed store creation
    5.4  Engine integration
         • Engine() without store — all 49 existing tests still pass
         • Engine(store=store) — successful workflow persisted
         • Engine(store=store) — failed task (STOP strategy) persisted
         • Engine(store=store) — BLOCKED cascade persisted
         • Engine(store=store) — SKIP strategy persisted
         • Engine(store=store) — RETRY strategy, attempts persisted
         • Engine(store=store) — parallel batch (multiple tasks, one run)
         • Engine(store=store) — multiple sequential re-runs same workflow
         • Engine(store=store) — persistence disabled (no store) leaves DB empty
    5.5  Recovery groundwork
         • Stored hierarchy is sufficient to reconstruct run summary
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from forge.core.engine import Engine
from forge.core.result import WorkflowStatus
from forge.core.task import ExecutionContext, FailureStrategy, Task, TaskStatus
from forge.core.workflow import Workflow
from forge.persistence import ExecutionStore
from forge.persistence.models import (
    TaskAttemptRecord,
    TaskRunRecord,
    WorkflowRunRecord,
    _from_json,
    _to_json,
)
from forge.persistence.schema import (
    SCHEMA_VERSION,
    get_schema_version,
    init_schema,
)
from forge.tasks.function_task import FunctionTask


# ── Helpers ───────────────────────────────────────────────────────────────────

class SuccessTask(Task):
    """Always succeeds and returns its name."""
    def execute(self, context: ExecutionContext) -> str:
        return f"done:{self.name}"


class FailTask(Task):
    """Always raises RuntimeError."""
    def execute(self, context: ExecutionContext) -> None:
        raise RuntimeError(f"deliberate failure in {self.name}")


class FlakyTask(Task):
    """Fails on the first N attempts, then succeeds."""
    def __init__(self, name: str, fail_times: int = 1, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self._fail_times = fail_times
        self._call_count = 0

    def execute(self, context: ExecutionContext) -> str:
        self._call_count += 1
        if self._call_count <= self._fail_times:
            raise RuntimeError(f"flaky attempt {self._call_count}")
        return "recovered"


def _silent_engine(**kwargs: Any) -> Engine:
    """Engine with console output suppressed."""
    return Engine(verbose=False, **kwargs)


def _simple_workflow(name: str = "TestWorkflow") -> tuple[Workflow, SuccessTask]:
    task = SuccessTask("Alpha")
    wf = Workflow(name)
    wf.add_task(task)
    return wf, task


# ─────────────────────────────────────────────────────────────────────────────
# 5.1  Schema
# ─────────────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_init_schema_creates_tables(self) -> None:
        """All expected tables must exist after init_schema()."""
        conn = sqlite3.connect(":memory:")
        init_schema(conn)

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "workflow_runs" in tables
        assert "task_runs" in tables
        assert "task_attempts" in tables
        assert "schema_version" in tables

    def test_init_schema_is_idempotent(self) -> None:
        """Calling init_schema() twice must not raise or duplicate rows."""
        conn = sqlite3.connect(":memory:")
        init_schema(conn)
        init_schema(conn)  # second call — must be safe

        version_rows = conn.execute("SELECT * FROM schema_version").fetchall()
        assert len(version_rows) == 1

    def test_schema_version_recorded(self) -> None:
        """schema_version table must contain the current SCHEMA_VERSION."""
        conn = sqlite3.connect(":memory:")
        init_schema(conn)
        assert get_schema_version(conn) == SCHEMA_VERSION

    def test_get_schema_version_on_blank_db(self) -> None:
        """get_schema_version() returns None on a completely blank database."""
        conn = sqlite3.connect(":memory:")
        assert get_schema_version(conn) is None

    def test_foreign_key_enforcement(self) -> None:
        """Inserting a task_run with an invalid run_id must raise an error."""
        conn = sqlite3.connect(":memory:")
        init_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute(
                """
                INSERT INTO task_runs (task_run_id, run_id, task_name, status,
                    attempt_count)
                VALUES ('t1', 'nonexistent-run', 'T', 'SUCCESS', 0)
                """
            )
            conn.commit()

    def test_schema_migration_v1_to_v2(self) -> None:
        """A v1 database missing workflow_id column is fully migrated to current version (v3)."""
        conn = sqlite3.connect(":memory:")
        # Create minimal v1 schema manually
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL);")
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (1, '2026-01-01T00:00:00Z');")
        conn.execute("""
            CREATE TABLE workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_seconds REAL,
                parameters TEXT NOT NULL DEFAULT '{}',
                metadata TEXT NOT NULL DEFAULT '{}',
                total_tasks INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                blocked_count INTEGER NOT NULL DEFAULT 0,
                cancelled_count INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.execute("INSERT INTO workflow_runs (run_id, workflow_name, status, started_at) VALUES ('v1_run_01', 'V1_WF', 'SUCCESS', '2026-01-01T00:00:00Z');")
        conn.commit()

        # Run init_schema (which triggers all migrations)
        init_schema(conn)

        # Should be fully migrated to current SCHEMA_VERSION (v3)
        assert get_schema_version(conn) == SCHEMA_VERSION
        columns = [row[1] for row in conn.execute("PRAGMA table_info(workflow_runs);").fetchall()]
        assert "workflow_id" in columns, "v1→v2 migration: workflow_id column missing"
        assert "worker_pid" in columns, "v2→v3 migration: worker_pid column missing"

        # Backfilled workflow_id = run_id
        row = conn.execute("SELECT run_id, workflow_id FROM workflow_runs WHERE run_id = 'v1_run_01';").fetchone()
        assert row[0] == "v1_run_01"
        assert row[1] == "v1_run_01"



# ─────────────────────────────────────────────────────────────────────────────
# 5.2  Models
# ─────────────────────────────────────────────────────────────────────────────

class TestModels:
    def test_workflow_run_record_round_trip(self) -> None:
        """WorkflowRunRecord survives a serialise → from_row round trip."""
        original = WorkflowRunRecord(
            run_id="run-001",
            workflow_name="ETL Pipeline",
            status="SUCCESS",
            started_at="2024-01-01T00:00:00+00:00",
            finished_at="2024-01-01T00:01:00+00:00",
            duration_seconds=60.0,
            parameters='{"batch": 1}',
            metadata='{"env": "prod"}',
            total_tasks=3,
            success_count=3,
        )
        row = (
            original.run_id, original.workflow_name, original.status,
            original.started_at, original.finished_at, original.duration_seconds,
            original.parameters, original.metadata,
            original.total_tasks, original.success_count, original.failed_count,
            original.skipped_count, original.blocked_count, original.cancelled_count,
        )
        restored = WorkflowRunRecord.from_row(row)
        assert restored.run_id == "run-001"
        assert restored.workflow_name == "ETL Pipeline"
        assert restored.success_count == 3
        assert restored.duration_seconds == 60.0

    def test_task_run_record_as_dict(self) -> None:
        """as_dict() deserialises the JSON output field correctly."""
        rec = TaskRunRecord(
            task_run_id="task-001",
            run_id="run-001",
            task_name="Load",
            status="SUCCESS",
            output=_to_json({"rows": 42}),
            attempt_count=1,
        )
        d = rec.as_dict()
        assert d["output"] == {"rows": 42}
        assert d["status"] == "SUCCESS"

    def test_task_attempt_record_round_trip(self) -> None:
        """TaskAttemptRecord from_row reconstructs all fields correctly."""
        row = (
            7, "task-001", 2, "FAILED",
            "2024-01-01T00:00:05+00:00", "2024-01-01T00:00:06+00:00",
            1.0,
            None, "boom", "Traceback..."
        )
        rec = TaskAttemptRecord.from_row(row)
        assert rec.id == 7
        assert rec.attempt_number == 2
        assert rec.status == "FAILED"
        assert rec.error_message == "boom"

    def test_json_helper_non_serialisable(self) -> None:
        """_to_json() falls back gracefully for non-JSON types."""
        result = _to_json(b"binary data")
        assert isinstance(result, str)

    def test_from_json_invalid(self) -> None:
        """_from_json() returns the raw string when JSON is malformed."""
        raw = "not-json{"
        assert _from_json(raw) == raw

    def test_from_json_none(self) -> None:
        assert _from_json(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# 5.3  ExecutionStore write / read API
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionStore:
    @pytest.fixture
    def store(self) -> ExecutionStore:
        return ExecutionStore.in_memory()

    def test_create_and_get_workflow_run(self, store: ExecutionStore) -> None:
        """create_workflow_run() then get_workflow_run() returns the same row."""
        store.create_workflow_run(
            run_id="run-A",
            workflow_name="MyWorkflow",
            status="RUNNING",
            parameters={"x": 1},
        )
        rec = store.get_workflow_run("run-A")
        assert rec is not None
        assert rec.run_id == "run-A"
        assert rec.workflow_name == "MyWorkflow"
        assert rec.status == "RUNNING"
        assert _from_json(rec.parameters) == {"x": 1}

    def test_complete_workflow_run(self, store: ExecutionStore) -> None:
        """complete_workflow_run() updates status and counters."""
        store.create_workflow_run(run_id="run-B", workflow_name="W", status="RUNNING")
        store.complete_workflow_run(
            run_id="run-B",
            status="SUCCESS",
            finished_at="2024-06-01T12:00:00+00:00",
            duration_seconds=5.5,
            total_tasks=2,
            success_count=2,
            failed_count=0,
            skipped_count=0,
            blocked_count=0,
            cancelled_count=0,
        )
        rec = store.get_workflow_run("run-B")
        assert rec.status == "SUCCESS"
        assert rec.duration_seconds == 5.5
        assert rec.total_tasks == 2
        assert rec.success_count == 2

    def test_save_and_get_task_run(self, store: ExecutionStore) -> None:
        """save_task_run() then get_task_run() returns the task row."""
        store.create_workflow_run(run_id="run-C", workflow_name="W", status="RUNNING")
        store.save_task_run(
            run_id="run-C",
            task_run_id="task-C1",
            task_name="Extract",
            status="SUCCESS",
            started_at="2024-01-01T00:00:00+00:00",
            finished_at="2024-01-01T00:00:01+00:00",
            duration_seconds=1.0,
            attempt_count=1,
            output="rows",
            error_message=None,
            error_traceback=None,
        )
        rec = store.get_task_run("task-C1")
        assert rec is not None
        assert rec.task_name == "Extract"
        assert rec.status == "SUCCESS"
        assert rec.attempt_count == 1

    def test_get_task_runs_for_workflow(self, store: ExecutionStore) -> None:
        """get_task_runs() returns all task runs for a given workflow run."""
        store.create_workflow_run(run_id="run-D", workflow_name="W", status="RUNNING")
        for i in range(3):
            store.save_task_run(
                run_id="run-D",
                task_run_id=f"task-D{i}",
                task_name=f"Task{i}",
                status="SUCCESS",
                started_at=None, finished_at=None,
                duration_seconds=None, attempt_count=1,
                output=None, error_message=None, error_traceback=None,
            )
        runs = store.get_task_runs("run-D")
        assert len(runs) == 3
        assert {r.task_name for r in runs} == {"Task0", "Task1", "Task2"}

    def test_save_task_attempt(self, store: ExecutionStore) -> None:
        """save_task_attempt() stores attempt detail and id is populated."""
        store.create_workflow_run(run_id="run-E", workflow_name="W", status="RUNNING")
        store.save_task_run(
            run_id="run-E", task_run_id="task-E1", task_name="T",
            status="FAILED", started_at=None, finished_at=None,
            duration_seconds=None, attempt_count=2,
            output=None, error_message="oops", error_traceback=None,
        )
        attempt = store.save_task_attempt(
            task_run_id="task-E1",
            attempt_number=1,
            status="FAILED",
            started_at="2024-01-01T00:00:00+00:00",
            finished_at="2024-01-01T00:00:01+00:00",
            duration_seconds=1.0,
            output=None,
            error_message="oops",
            error_traceback="tb...",
        )
        assert attempt.id is not None and attempt.id > 0

        attempts = store.get_task_attempts("task-E1")
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].error_message == "oops"

    def test_list_workflow_runs_no_filter(self, store: ExecutionStore) -> None:
        """list_workflow_runs() returns all runs when no filter applied."""
        for i in range(5):
            store.create_workflow_run(run_id=f"run-{i}", workflow_name=f"WF{i}", status="SUCCESS")
        runs = store.list_workflow_runs()
        assert len(runs) == 5

    def test_list_workflow_runs_filter_name(self, store: ExecutionStore) -> None:
        """list_workflow_runs(workflow_name=...) filters correctly."""
        store.create_workflow_run(run_id="r1", workflow_name="Alpha", status="SUCCESS")
        store.create_workflow_run(run_id="r2", workflow_name="Beta", status="SUCCESS")
        store.create_workflow_run(run_id="r3", workflow_name="Alpha", status="FAILED")

        alpha_runs = store.list_workflow_runs(workflow_name="Alpha")
        assert len(alpha_runs) == 2
        assert all(r.workflow_name == "Alpha" for r in alpha_runs)

    def test_list_workflow_runs_filter_status(self, store: ExecutionStore) -> None:
        """list_workflow_runs(status=...) filters by terminal status."""
        store.create_workflow_run(run_id="r1", workflow_name="W", status="SUCCESS")
        store.create_workflow_run(run_id="r2", workflow_name="W", status="FAILED")
        store.create_workflow_run(run_id="r3", workflow_name="W", status="SUCCESS")

        successes = store.list_workflow_runs(status="SUCCESS")
        assert len(successes) == 2

    def test_list_workflow_runs_pagination(self, store: ExecutionStore) -> None:
        """limit and offset work correctly."""
        for i in range(10):
            store.create_workflow_run(run_id=f"run-{i}", workflow_name="W", status="SUCCESS")
        page1 = store.list_workflow_runs(limit=4, offset=0)
        page2 = store.list_workflow_runs(limit=4, offset=4)
        assert len(page1) == 4
        assert len(page2) == 4
        # No overlap
        ids1 = {r.run_id for r in page1}
        ids2 = {r.run_id for r in page2}
        assert ids1.isdisjoint(ids2)

    def test_count_workflow_runs(self, store: ExecutionStore) -> None:
        assert store.count_workflow_runs() == 0
        store.create_workflow_run(run_id="r1", workflow_name="W", status="SUCCESS")
        store.create_workflow_run(run_id="r2", workflow_name="W2", status="FAILED")
        assert store.count_workflow_runs() == 2
        assert store.count_workflow_runs(workflow_name="W") == 1

    def test_get_workflow_run_not_found(self, store: ExecutionStore) -> None:
        assert store.get_workflow_run("does-not-exist") is None

    def test_get_task_run_not_found(self, store: ExecutionStore) -> None:
        assert store.get_task_run("does-not-exist") is None

    def test_file_backed_store_creation(self, tmp_path: Path) -> None:
        """ExecutionStore.create() creates the DB file and initialises schema."""
        db_file = tmp_path / "subdir" / "forge.db"
        store = ExecutionStore.create(db_file)
        assert db_file.exists()
        store.create_workflow_run(run_id="file-run", workflow_name="W", status="SUCCESS")
        rec = store.get_workflow_run("file-run")
        assert rec is not None
        store.close()

    def test_context_manager(self) -> None:
        """ExecutionStore works as a context manager."""
        with ExecutionStore.in_memory() as store:
            store.create_workflow_run(run_id="cm-run", workflow_name="W", status="SUCCESS")
            assert store.get_workflow_run("cm-run") is not None


# ─────────────────────────────────────────────────────────────────────────────
# 5.4  Engine integration
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineIntegration:
    """Verify that Engine(store=store) persists correctly without breaking Engine()."""

    # ── Baseline: persistence disabled ────────────────────────────────────────

    def test_engine_without_store_still_works(self) -> None:
        """Engine() without a store runs normally and does not persist."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine()  # no store passed

        wf, _ = _simple_workflow()
        result = engine.run(wf)

        assert result.status == WorkflowStatus.SUCCESS
        # Nothing should have been written
        assert store.count_workflow_runs() == 0

    # ── Successful workflow ───────────────────────────────────────────────────

    def test_successful_workflow_persisted(self) -> None:
        """A SUCCESS run records workflow_run + task_runs + task_attempts."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        t1 = SuccessTask("Step1")
        t2 = SuccessTask("Step2")
        t2.add_dependency(t1)
        wf = Workflow("PersistTest")
        wf.add_tasks(t1, t2)

        result = engine.run(wf)
        assert result.status == WorkflowStatus.SUCCESS

        run_rec = store.get_workflow_run(result.workflow_id)
        assert run_rec is not None
        assert run_rec.status == "SUCCESS"
        assert run_rec.total_tasks == 2
        assert run_rec.success_count == 2
        assert run_rec.duration_seconds is not None and run_rec.duration_seconds >= 0

        task_runs = store.get_task_runs(result.workflow_id)
        assert len(task_runs) == 2
        assert all(tr.status == "SUCCESS" for tr in task_runs)

        for tr in task_runs:
            attempts = store.get_task_attempts(tr.task_run_id)
            assert len(attempts) == 1
            assert attempts[0].status == "SUCCESS"

    # ── Failed task (STOP strategy) ───────────────────────────────────────────

    def test_failed_task_persisted(self) -> None:
        """FAILED status and error message are persisted for failed tasks."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        fail = FailTask("Explode", failure_strategy=FailureStrategy.STOP)
        wf = Workflow("FailWorkflow")
        wf.add_task(fail)

        result = engine.run(wf)
        assert result.status == WorkflowStatus.FAILED

        run_rec = store.get_workflow_run(result.workflow_id)
        assert run_rec.status == "FAILED"
        assert run_rec.failed_count == 1

        task_runs = store.get_task_runs(result.workflow_id)
        failed_tr = next(tr for tr in task_runs if tr.task_name == "Explode")
        assert failed_tr.status == "FAILED"
        assert failed_tr.error_message is not None

        attempts = store.get_task_attempts(failed_tr.task_run_id)
        assert len(attempts) == 1
        assert attempts[0].status == "FAILED"
        assert "deliberate failure" in attempts[0].error_message

    # ── BLOCKED cascade ───────────────────────────────────────────────────────

    def test_blocked_tasks_persisted(self) -> None:
        """BLOCKED downstream tasks are saved after an upstream STOP failure."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        fail = FailTask("Root", failure_strategy=FailureStrategy.STOP)
        child = SuccessTask("Child")
        child.add_dependency(fail)

        wf = Workflow("BlockTest")
        wf.add_tasks(fail, child)

        result = engine.run(wf)
        assert result.status == WorkflowStatus.FAILED

        task_runs = store.get_task_runs(result.workflow_id)
        statuses = {tr.task_name: tr.status for tr in task_runs}
        assert statuses["Root"] == "FAILED"
        assert statuses["Child"] == "BLOCKED"

        run_rec = store.get_workflow_run(result.workflow_id)
        assert run_rec.blocked_count >= 1

    # ── SKIP strategy ─────────────────────────────────────────────────────────

    def test_skip_strategy_persisted(self) -> None:
        """SKIPPED tasks are recorded with correct status."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        skip_task = FailTask("SkipMe", failure_strategy=FailureStrategy.SKIP)
        wf = Workflow("SkipWorkflow")
        wf.add_task(skip_task)

        result = engine.run(wf)

        task_runs = store.get_task_runs(result.workflow_id)
        assert task_runs[0].status == "SKIPPED"

        run_rec = store.get_workflow_run(result.workflow_id)
        assert run_rec.skipped_count == 1

    # ── RETRY strategy ────────────────────────────────────────────────────────

    def test_retry_attempts_persisted(self) -> None:
        """Each retry attempt is stored as a separate task_attempts row."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        flaky = FlakyTask(
            "Flaky",
            fail_times=2,
            failure_strategy=FailureStrategy.RETRY,
            max_retries=3,
        )
        wf = Workflow("RetryWorkflow")
        wf.add_task(flaky)

        result = engine.run(wf)
        assert result.status == WorkflowStatus.SUCCESS

        task_runs = store.get_task_runs(result.workflow_id)
        assert len(task_runs) == 1
        tr = task_runs[0]
        assert tr.status == "SUCCESS"
        assert tr.attempt_count == 3  # 2 failures + 1 success

        attempts = store.get_task_attempts(tr.task_run_id)
        assert len(attempts) == 3
        assert attempts[0].status == "FAILED"
        assert attempts[1].status == "FAILED"
        assert attempts[2].status == "SUCCESS"

    # ── Parallel batch ────────────────────────────────────────────────────────

    def test_parallel_batch_persisted(self) -> None:
        """All tasks in a parallel batch are persisted under the same run."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store, max_workers=4)

        root = SuccessTask("Root")
        branches = [SuccessTask(f"Branch{i}") for i in range(4)]
        for b in branches:
            b.add_dependency(root)

        wf = Workflow("ParallelWorkflow")
        wf.add_task(root)
        for b in branches:
            wf.add_task(b)

        result = engine.run(wf)
        assert result.status == WorkflowStatus.SUCCESS

        task_runs = store.get_task_runs(result.workflow_id)
        assert len(task_runs) == 5  # root + 4 branches
        assert all(tr.status == "SUCCESS" for tr in task_runs)

    # ── Multiple sequential re-runs ───────────────────────────────────────────

    def test_multiple_runs_stored_independently(self) -> None:
        """Running two separate Workflow instances stores two independent run rows."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        # Two separate instances → two unique workflow_ids
        wf1, _ = _simple_workflow("RerunWorkflow")
        wf2, _ = _simple_workflow("RerunWorkflow")

        result1 = engine.run(wf1)
        result2 = engine.run(wf2)

        assert result1.workflow_id != result2.workflow_id

        runs = store.list_workflow_runs(workflow_name="RerunWorkflow")
        assert len(runs) == 2
        assert store.count_workflow_runs(workflow_name="RerunWorkflow") == 2

        # Each run has its own task rows
        tasks1 = store.get_task_runs(result1.workflow_id)
        tasks2 = store.get_task_runs(result2.workflow_id)
        assert len(tasks1) == 1
        assert len(tasks2) == 1

    def test_same_workflow_instance_multiple_runs(self) -> None:
        """Executing the exact same Workflow instance twice creates distinct run_ids and persists both."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        wf, _ = _simple_workflow("StableWorkflow")

        r1 = engine.run(wf)
        r2 = engine.run(wf)

        # Same definition ID
        assert r1.workflow_id == r2.workflow_id == wf.workflow_id
        # Different execution IDs
        assert r1.run_id != r2.run_id

        # Both persisted under the same workflow_id
        runs = store.list_workflow_runs(workflow_id=wf.workflow_id)
        assert len(runs) == 2
        run_ids = {r.run_id for r in runs}
        assert run_ids == {r1.run_id, r2.run_id}

        # Each run has independent task records
        tasks_r1 = store.get_task_runs(r1.run_id)
        tasks_r2 = store.get_task_runs(r2.run_id)
        assert len(tasks_r1) == 1
        assert len(tasks_r2) == 1
        assert tasks_r1[0].run_id == r1.run_id
        assert tasks_r2[0].run_id == r2.run_id


    # ── Parameter injection ───────────────────────────────────────────────────

    def test_runtime_parameters_persisted(self) -> None:
        """Parameters passed to Engine.run() are stored in the workflow run row."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        wf, _ = _simple_workflow("ParamWorkflow")
        result = engine.run(wf, parameters={"env": "staging", "batch": 42})

        run_rec = store.get_workflow_run(result.workflow_id)
        params = _from_json(run_rec.parameters)
        assert params.get("env") == "staging"
        assert params.get("batch") == 42

    # ── Empty workflow ────────────────────────────────────────────────────────

    def test_empty_workflow_persisted(self) -> None:
        """An empty workflow (no tasks) still creates a SUCCESS run row."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        wf = Workflow("Empty")
        result = engine.run(wf)
        assert result.status == WorkflowStatus.SUCCESS

        run_rec = store.get_workflow_run(result.workflow_id)
        assert run_rec is not None
        assert run_rec.status == "SUCCESS"
        assert run_rec.total_tasks == 0

    # ── List ordering ────────────────────────────────────────────────────────

    def test_list_runs_most_recent_first(self) -> None:
        """list_workflow_runs() returns newest run first."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        # Separate instances so each gets its own unique workflow_id
        wf1, _ = _simple_workflow("OrderTest")
        wf2, _ = _simple_workflow("OrderTest")

        r1 = engine.run(wf1)
        r2 = engine.run(wf2)

        runs = store.list_workflow_runs(workflow_name="OrderTest")
        # Most recent is first (ORDER BY started_at DESC)
        assert runs[0].run_id == r2.run_id
        assert runs[0].workflow_id == r2.workflow_id
        assert runs[1].run_id == r1.run_id
        assert runs[1].workflow_id == r1.workflow_id

    def test_list_runs_equal_timestamps_deterministic_ordering(self) -> None:
        """list_workflow_runs() uses insertion order (rowid) when started_at timestamps tie."""
        store = ExecutionStore.in_memory()
        same_time = "2026-01-01T12:00:00.000000+00:00"

        rec1 = store.create_workflow_run(
            run_id="run_first_inserted",
            workflow_id="wf_tied_1",
            workflow_name="TieTest",
            status="SUCCESS",
            started_at=same_time,
        )
        rec2 = store.create_workflow_run(
            run_id="run_second_inserted",
            workflow_id="wf_tied_2",
            workflow_name="TieTest",
            status="SUCCESS",
            started_at=same_time,
        )

        runs = store.list_workflow_runs(workflow_name="TieTest")
        assert runs[0].run_id == rec2.run_id
        assert runs[1].run_id == rec1.run_id


# ─────────────────────────────────────────────────────────────────────────────
# 5.5  Recovery groundwork
# ─────────────────────────────────────────────────────────────────────────────

class TestRecoveryGroundwork:
    """Verify the stored data is sufficient to reconstruct run summaries."""

    def test_hierarchy_completeness(self) -> None:
        """For a failed run with retries, the DB contains all hierarchy levels."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        flaky = FlakyTask(
            "FlakyLoad",
            fail_times=1,
            failure_strategy=FailureStrategy.RETRY,
            max_retries=2,
        )
        ok = SuccessTask("Notify")
        ok.add_dependency(flaky)

        wf = Workflow("ETL Pipeline")
        wf.add_tasks(flaky, ok)

        result = engine.run(wf)
        assert result.status == WorkflowStatus.SUCCESS

        # Workflow level
        run_rec = store.get_workflow_run(result.workflow_id)
        assert run_rec.workflow_name == "ETL Pipeline"
        assert run_rec.success_count == 2

        # Task level
        task_runs = store.get_task_runs(result.workflow_id)
        assert len(task_runs) == 2
        flaky_run = next(tr for tr in task_runs if tr.task_name == "FlakyLoad")
        ok_run = next(tr for tr in task_runs if tr.task_name == "Notify")
        assert flaky_run.attempt_count == 2

        # Attempt level for the flaky task
        attempts = store.get_task_attempts(flaky_run.task_run_id)
        assert len(attempts) == 2
        assert attempts[0].status == "FAILED"
        assert attempts[1].status == "SUCCESS"

        # Clean attempt for the notify task
        ok_attempts = store.get_task_attempts(ok_run.task_run_id)
        assert len(ok_attempts) == 1
        assert ok_attempts[0].status == "SUCCESS"

    def test_summary_reconstruction(self) -> None:
        """All fields needed for 'forge run inspect <id>' are stored."""
        store = ExecutionStore.in_memory()
        engine = _silent_engine(store=store)

        wf, _ = _simple_workflow("InspectWorkflow")
        result = engine.run(wf)

        run_rec = store.get_workflow_run(result.workflow_id)
        # Every field the CLI will need
        assert run_rec.run_id is not None
        assert run_rec.workflow_name == "InspectWorkflow"
        assert run_rec.status in {s.value for s in WorkflowStatus}
        assert run_rec.started_at is not None
        assert run_rec.finished_at is not None
        assert run_rec.duration_seconds is not None
        assert run_rec.total_tasks >= 0

        task_runs = store.get_task_runs(run_rec.run_id)
        for tr in task_runs:
            assert tr.task_run_id is not None
            assert tr.task_name is not None
            assert tr.status is not None
            attempts = store.get_task_attempts(tr.task_run_id)
            for att in attempts:
                assert att.attempt_number >= 1
                assert att.started_at is not None


# =============================================================================
# Phase 8.1 — Persistence Reliability
# =============================================================================

class TestPhase81PersistenceReliability:
    """Phase 8.1 tests: WAL mode, busy_timeout, worker_pid stamping, orphan recovery."""

    # ── 8.1.1 WAL mode & busy_timeout ─────────────────────────────────────────

    def test_wal_mode_enabled_on_file_backed_store(self, tmp_path: Path) -> None:
        """File-backed ExecutionStore uses WAL journal mode."""
        db = tmp_path / "forge_wal_test.db"
        with ExecutionStore.create(db) as store:
            mode = store._conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode == "wal", f"Expected 'wal', got '{mode}'"

    def test_busy_timeout_set_on_file_backed_store(self, tmp_path: Path) -> None:
        """File-backed ExecutionStore has a non-zero busy_timeout."""
        db = tmp_path / "forge_busy_test.db"
        with ExecutionStore.create(db) as store:
            timeout = store._conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert timeout >= 1000, f"busy_timeout should be >= 1000ms, got {timeout}"

    def test_in_memory_store_wal_mode_graceful(self) -> None:
        """In-memory stores gracefully handle WAL PRAGMA (SQLite returns 'memory')."""
        # In-memory DBs can't use WAL; SQLite returns 'memory' silently.
        # The important thing is that store creation does not raise.
        store = ExecutionStore.in_memory()
        mode = store._conn.execute("PRAGMA journal_mode;").fetchone()[0]
        # 'memory' is the expected result for :memory: databases
        assert mode in ("wal", "memory")
        store.close()

    # ── 8.1.2 Schema v3 — worker_pid column ───────────────────────────────────

    def test_worker_pid_column_present(self) -> None:
        """Schema v3 includes the worker_pid column in workflow_runs."""
        conn = sqlite3.connect(":memory:")
        init_schema(conn)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(workflow_runs);").fetchall()]
        assert "worker_pid" in columns

    def test_v2_to_v3_migration_adds_worker_pid(self) -> None:
        """A v2 database missing worker_pid is migrated to v3 on init_schema."""
        conn = sqlite3.connect(":memory:")
        # Build a v2 schema manually (has workflow_id but not worker_pid)
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL);")
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (2, '2026-01-01T00:00:00Z');")
        conn.execute("""
            CREATE TABLE workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_seconds REAL,
                parameters TEXT NOT NULL DEFAULT '{}',
                metadata TEXT NOT NULL DEFAULT '{}',
                total_tasks INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                blocked_count INTEGER NOT NULL DEFAULT 0,
                cancelled_count INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.commit()

        init_schema(conn)

        assert get_schema_version(conn) == SCHEMA_VERSION
        columns = [row[1] for row in conn.execute("PRAGMA table_info(workflow_runs);").fetchall()]
        assert "worker_pid" in columns

    # ── 8.1.3 create_workflow_run stamps worker_pid ───────────────────────────

    def test_create_workflow_run_stamps_pid(self) -> None:
        """create_workflow_run() writes os.getpid() as worker_pid."""
        import os
        store = ExecutionStore.in_memory()
        rec = store.create_workflow_run(
            run_id="pid-test-run",
            workflow_name="PIDTest",
            status="RUNNING",
        )
        assert rec.worker_pid == os.getpid()

        # Also verify it roundtrips through the DB
        fetched = store.get_workflow_run("pid-test-run")
        assert fetched is not None
        assert fetched.worker_pid == os.getpid()
        store.close()

    # ── 8.1.4 recover_interrupted_runs — live process not touched ─────────────

    def test_recover_does_not_touch_live_process_runs(self) -> None:
        """recover_interrupted_runs() leaves RUNNING rows owned by a live PID untouched."""
        import os
        store = ExecutionStore.in_memory()
        # Simulate a run owned by the current (live) process
        store.create_workflow_run(
            run_id="live-run-001",
            workflow_name="LiveWF",
            status="RUNNING",
        )
        recovered = store.recover_interrupted_runs()
        assert "live-run-001" not in recovered

        # Row should still be RUNNING
        rec = store.get_workflow_run("live-run-001")
        assert rec is not None
        assert rec.status == "RUNNING"
        store.close()

    def test_recover_marks_dead_pid_runs_as_failed(self) -> None:
        """recover_interrupted_runs() marks RUNNING rows with dead PIDs as FAILED."""
        store = ExecutionStore.in_memory()

        # Insert a RUNNING row with a deliberately nonexistent PID.
        # PID 99999999 is almost certainly not a real process.
        dead_pid = 99_999_999
        with store._transaction() as cur:
            cur.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_id, workflow_name, status, started_at,
                    parameters, metadata, worker_pid
                ) VALUES (?, ?, ?, 'RUNNING', '2026-01-01T00:00:00Z', '{}', '{}', ?)
                """,
                ("orphan-001", "orphan-001", "OrphanWF", dead_pid),
            )

        recovered = store.recover_interrupted_runs()
        assert "orphan-001" in recovered

        rec = store.get_workflow_run("orphan-001")
        assert rec is not None
        assert rec.status == "FAILED"
        store.close()

    def test_recover_skips_null_pid_rows_conservatively(self) -> None:
        """recover_interrupted_runs() conservatively skips rows with NULL worker_pid."""
        store = ExecutionStore.in_memory()
        # Insert a RUNNING row with no PID (pre-v3 legacy row)
        with store._transaction() as cur:
            cur.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_id, workflow_name, status, started_at,
                    parameters, metadata, worker_pid
                ) VALUES ('legacy-001', 'legacy-001', 'LegacyWF', 'RUNNING',
                          '2026-01-01T00:00:00Z', '{}', '{}', NULL)
                """
            )

        recovered = store.recover_interrupted_runs()
        assert "legacy-001" not in recovered

        rec = store.get_workflow_run("legacy-001")
        assert rec is not None
        assert rec.status == "RUNNING"  # left untouched
        store.close()

    def test_recover_does_not_affect_completed_runs(self) -> None:
        """recover_interrupted_runs() only targets RUNNING status rows."""
        store = ExecutionStore.in_memory()
        dead_pid = 99_999_999
        # Insert a completed run with a dead PID — should not be recovered
        with store._transaction() as cur:
            cur.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_id, workflow_name, status, started_at,
                    parameters, metadata, worker_pid
                ) VALUES ('done-001', 'done-001', 'DoneWF', 'SUCCESS',
                          '2026-01-01T00:00:00Z', '{}', '{}', ?)
                """,
                (dead_pid,),
            )

        recovered = store.recover_interrupted_runs()
        assert "done-001" not in recovered
        rec = store.get_workflow_run("done-001")
        assert rec.status == "SUCCESS"  # unchanged
        store.close()

    def test_recover_empty_db_returns_empty_list(self) -> None:
        """recover_interrupted_runs() returns [] when there are no RUNNING rows."""
        store = ExecutionStore.in_memory()
        assert store.recover_interrupted_runs() == []
        store.close()

    # ── 8.1.6 Multi-thread concurrent writes ──────────────────────────────────

    def test_concurrent_writes_from_multiple_threads(self) -> None:
        """Multiple threads can write task runs concurrently without raising."""
        import threading
        store = ExecutionStore.in_memory()
        store.create_workflow_run(
            run_id="mt-run-001",
            workflow_name="MultiThreadWF",
            status="RUNNING",
        )

        errors: list[Exception] = []

        def write_task(i: int) -> None:
            try:
                store.save_task_run(
                    run_id="mt-run-001",
                    task_run_id=f"task-{i:03d}",
                    task_name=f"Task{i}",
                    status="SUCCESS",
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                    duration_seconds=1.0,
                    attempt_count=1,
                    output={"result": i},
                    error_message=None,
                    error_traceback=None,
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write_task, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        task_runs = store.get_task_runs("mt-run-001")
        assert len(task_runs) == 20
        store.close()

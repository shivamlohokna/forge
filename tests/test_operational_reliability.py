"""Tests for Forge Phase 8: Operational Reliability.

Covers:
- Graceful shutdown and interruption handling (SIGINT / KeyboardInterrupt, engine state persistence)
- Responsive cancellation during retry delays
- ShellTask subprocess cleanup and reap on termination
- SQLite durability: WAL mode, synchronous=NORMAL, and busy timeout retry
- Secret masking in parameters, metadata, free-form text, URLs, and persisted error messages
- Cascaded orphan recovery across workflow_runs, task_runs, and task_attempts
- Diagnostic health checks in forge doctor (integrity, journal mode, orphan detection)
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from forge import (
    Engine,
    ExecutionContext,
    FailureStrategy,
    FunctionTask,
    ShellTask,
    TaskResult,
    TaskStatus,
    Workflow,
    WorkflowStatus,
)
from forge.cli.commands import doctor_command, run_command
from forge.core.engine import EventType
from forge.persistence import ExecutionStore
from forge.persistence.schema import init_schema
from forge.utils.sanitizer import (
    MASK,
    sanitize,
    sanitize_error,
    sanitize_text,
)


class TestOperationalReliability(unittest.TestCase):
    """Phase 8 operational safety, secret masking, and recovery test suite."""

    # =========================================================================
    # 1. Graceful Shutdown & Interruption Handling
    # =========================================================================

    def test_keyboard_interrupt_marks_workflow_cancelled_and_persists(self) -> None:
        """When KeyboardInterrupt is raised during execution, the engine finalizes and persists CANCELLED status."""
        store = ExecutionStore.in_memory()
        engine = Engine(verbose=False, store=store)

        def interrupt_fn(ctx: ExecutionContext) -> None:
            raise KeyboardInterrupt("Simulated user Ctrl-C")

        wf = Workflow("InterruptWF")
        t1 = FunctionTask("InterruptTask", fn=interrupt_fn)
        t2 = FunctionTask("PendingTask", fn=lambda ctx: "never run")
        t2.depends_on(t1)
        wf.add_task(t1).add_task(t2)

        with self.assertRaises(KeyboardInterrupt):
            engine.run(wf)

        self.assertEqual(wf.status, WorkflowStatus.CANCELLED)

        # Check in persistence store: run must be recorded as CANCELLED, not left in RUNNING
        runs = store.list_workflow_runs(workflow_name="InterruptWF")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "CANCELLED")
        store.close()

    def test_cancellation_during_retry_delay_is_responsive(self) -> None:
        """Engine cancellation breaks immediately out of retry sleep delays."""
        engine = Engine(verbose=False)

        def fail_fn(ctx: ExecutionContext) -> None:
            raise RuntimeError("Temporary failure")

        wf = Workflow("RetryCancelWF")
        task = FunctionTask(
            "RetryTask",
            fn=fail_fn,
            max_retries=3,
            retry_delay=5.0,  # 5-second delay
            failure_strategy=FailureStrategy.RETRY,
        )
        wf.add_task(task)

        # Spawn a thread to cancel the engine shortly after it starts
        def async_cancel() -> None:
            time.sleep(0.15)
            engine.cancel()

        threading.Thread(target=async_cancel, daemon=True).start()

        start = time.perf_counter()
        result = engine.run(wf)
        elapsed = time.perf_counter() - start

        # Should finish well under the 5-second retry delay
        self.assertLess(elapsed, 2.0)
        self.assertEqual(result.status, WorkflowStatus.CANCELLED)

    def test_cli_run_keyboard_interrupt_returns_130(self) -> None:
        """CLI run_command catches KeyboardInterrupt cleanly and returns exit code 130 without traceback."""
        with patch("forge.cli.commands.Engine.run", side_effect=KeyboardInterrupt):
            with patch("forge.cli.commands.load_workflow", return_value=Workflow("TestWF")):
                stderr_buf = io.StringIO()
                with patch("sys.stderr", stderr_buf):
                    exit_code = run_command("dummy.json")
                self.assertEqual(exit_code, 130)
                self.assertIn("interrupted", stderr_buf.getvalue().lower())

    def test_shell_task_terminates_subprocess_on_exception(self) -> None:
        """ShellTask safely terminates the child process when an exception occurs."""
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = KeyboardInterrupt("Interrupt during communicate")

        with patch("subprocess.Popen", return_value=mock_proc):
            task = ShellTask("MockShell", command="echo test")
            ctx = ExecutionContext(task_id="t1", task_name="MockShell")
            with self.assertRaises(KeyboardInterrupt):
                task.execute(ctx)

            # mock_proc.kill must have been called
            mock_proc.kill.assert_called_once()

    # =========================================================================
    # 2. SQLite Durability, WAL Mode & Locking Behavior
    # =========================================================================

    def test_wal_mode_and_synchronous_normal(self) -> None:
        """File-backed stores enable WAL journal mode and PRAGMA synchronous = NORMAL."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = Path(tmp_dir) / "test_durability.db"
            with ExecutionStore.create(db_file) as store:
                journal_mode = store._conn.execute("PRAGMA journal_mode;").fetchone()[0]
                sync_mode = store._conn.execute("PRAGMA synchronous;").fetchone()[0]
                busy_timeout = store._conn.execute("PRAGMA busy_timeout;").fetchone()[0]

                self.assertEqual(journal_mode.lower(), "wal")
                # In SQLite, PRAGMA synchronous returns 1 for NORMAL
                self.assertEqual(sync_mode, 1)
                self.assertGreaterEqual(busy_timeout, 5000)

    def test_transaction_busy_retry_recovers(self) -> None:
        """_transaction() retries on transient 'database is locked' errors before failing."""
        store = ExecutionStore.in_memory()
        real_conn = store._conn

        class ConnProxy:
            def __init__(self, target):
                self._target = target
                self.commit_attempts = 0

            def cursor(self):
                return self._target.cursor()

            def commit(self):
                self.commit_attempts += 1
                if self.commit_attempts < 3:
                    raise sqlite3.OperationalError("database is locked")
                return self._target.commit()

            def rollback(self):
                return self._target.rollback()

            def __getattr__(self, name):
                return getattr(self._target, name)

        proxy = ConnProxy(real_conn)
        store._conn = proxy

        try:
            with store._transaction(max_retries=5, base_delay=0.01) as cur:
                cur.execute("SELECT 1;")
            self.assertEqual(proxy.commit_attempts, 3)
        finally:
            store._conn = real_conn
            store.close()

    # =========================================================================
    # 3. Secret Masking in Logs, Persisted Results & Errors
    # =========================================================================

    def test_sanitize_text_urls_with_embedded_credentials(self) -> None:
        """URLs containing username:password have the password masked."""
        raw = "Connecting to https://admin:SuperSecretPass123@api.internal.org/v1/data"
        sanitized = sanitize_text(raw)
        self.assertNotIn("SuperSecretPass123", sanitized)
        self.assertIn("admin:***", sanitized)
        self.assertIn("/v1/data", sanitized)

    def test_sanitize_text_bearer_tokens(self) -> None:
        """Bearer tokens in header logs or error strings are masked."""
        raw = "HTTP 401 Unauthorized: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
        sanitized = sanitize_text(raw)
        self.assertNotIn("eyJhbGciOi", sanitized)
        self.assertIn("Bearer ***", sanitized)

    def test_sanitize_text_key_value_assignments(self) -> None:
        """Common key=value or key:value assignments in error strings are masked."""
        raw = "Connection failed: api_key=abc123secret and password: mySecretPassword"
        sanitized = sanitize_text(raw)
        self.assertNotIn("abc123secret", sanitized)
        self.assertNotIn("mySecretPassword", sanitized)
        self.assertIn("api_key=***", sanitized)
        self.assertIn("password:***", sanitized)

    def test_create_workflow_run_sanitizes_parameters_and_metadata(self) -> None:
        """Parameters and metadata written to workflow_runs table are masked."""
        store = ExecutionStore.in_memory()
        raw_params = {
            "api_token": "ghp_VerySecretTokenValue",
            "db_password": "super_secret_db_pass",
            "host": "db.example.com",
            "port": 5432,
        }
        raw_meta = {
            "credentials": {"secret_key": "raw_secret"},
            "config": {"auth_token": "secret_token"},
            "owner": "deploy-agent",
        }

        rec = store.create_workflow_run(
            run_id="sec-run-001",
            workflow_name="SecretWorkflow",
            status="RUNNING",
            parameters=raw_params,
            metadata=raw_meta,
        )

        persisted = store.get_workflow_run("sec-run-001")
        self.assertIsNotNone(persisted)

        persisted_params = json.loads(persisted.parameters)
        self.assertEqual(persisted_params["api_token"], MASK)
        self.assertEqual(persisted_params["db_password"], MASK)
        self.assertEqual(persisted_params["host"], "db.example.com")
        self.assertEqual(persisted_params["port"], 5432)

        persisted_meta = json.loads(persisted.metadata)
        self.assertEqual(persisted_meta["credentials"], MASK)
        self.assertEqual(persisted_meta["config"]["auth_token"], MASK)
        self.assertEqual(persisted_meta["owner"], "deploy-agent")
        store.close()

    def test_save_task_run_and_attempt_sanitize_error_message(self) -> None:
        """Error messages containing passwords or bearer tokens are sanitized upon save."""
        store = ExecutionStore.in_memory()
        store.create_workflow_run("run-err-01", "ErrWF", "RUNNING")

        secret_err = "Failed request to https://user:secretpass@api.test/ with Bearer secrettoken123"

        store.save_task_run(
            run_id="run-err-01",
            task_run_id="tr-01",
            task_name="Task1",
            status="FAILED",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration_seconds=1.0,
            attempt_count=1,
            output=None,
            error_message=secret_err,
            error_traceback=None,
        )

        store.save_task_attempt(
            task_run_id="tr-01",
            attempt_number=1,
            status="FAILED",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration_seconds=1.0,
            output=None,
            error_message=secret_err,
            error_traceback=None,
        )

        tr = store.get_task_run("tr-01")
        self.assertIsNotNone(tr)
        self.assertNotIn("secretpass", tr.error_message)
        self.assertNotIn("secrettoken123", tr.error_message)
        self.assertIn("user:***", tr.error_message)

        attempts = store.get_task_attempts("tr-01")
        self.assertEqual(len(attempts), 1)
        self.assertNotIn("secretpass", attempts[0].error_message)
        store.close()

    # =========================================================================
    # 4. Cascaded Orphan Recovery
    # =========================================================================

    def test_recover_interrupted_runs_cascades_to_task_runs_and_attempts(self) -> None:
        """When an orphaned workflow run is recovered, associated running tasks and attempts are marked FAILED."""
        store = ExecutionStore.in_memory()
        dead_pid = 99_999_999

        # 1. Insert orphaned workflow run
        with store._transaction() as cur:
            cur.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_id, workflow_name, status, started_at,
                    parameters, metadata, worker_pid
                ) VALUES ('orphan-cascade-01', 'wf-01', 'OrphanWF', 'RUNNING',
                          '2026-01-01T00:00:00Z', '{}', '{}', ?)
                """,
                (dead_pid,),
            )
            # 2. Insert running task run
            cur.execute(
                """
                INSERT INTO task_runs (
                    task_run_id, run_id, task_name, status, started_at, attempt_count
                ) VALUES ('tr-c1', 'orphan-cascade-01', 'TaskC1', 'RUNNING', '2026-01-01T00:00:00Z', 1)
                """
            )
            # 3. Insert running task attempt
            cur.execute(
                """
                INSERT INTO task_attempts (
                    task_run_id, attempt_number, status, started_at
                ) VALUES ('tr-c1', 1, 'RUNNING', '2026-01-01T00:00:00Z')
                """
            )

        recovered = store.recover_interrupted_runs()
        self.assertIn("orphan-cascade-01", recovered)

        # Verify workflow run is FAILED
        wf_rec = store.get_workflow_run("orphan-cascade-01")
        self.assertEqual(wf_rec.status, "FAILED")

        # Verify task run cascaded to FAILED
        tr_rec = store.get_task_run("tr-c1")
        self.assertEqual(tr_rec.status, "FAILED")
        self.assertIn("Interrupted", tr_rec.error_message)

        # Verify task attempt cascaded to FAILED
        attempts = store.get_task_attempts("tr-c1")
        self.assertEqual(attempts[0].status, "FAILED")
        self.assertIn("Interrupted", attempts[0].error_message)
        store.close()

    # =========================================================================
    # 5. Doctor Health Diagnostics
    # =========================================================================

    def test_doctor_command_inspects_sqlite_integrity_and_journal(self) -> None:
        """doctor_command reports SQLite integrity, journal mode, and active runs."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "doctor_test.db"
            # Initialize a healthy store
            with ExecutionStore.create(db_path) as store:
                pass

            output_buf = io.StringIO()
            with patch("sys.stdout", output_buf):
                code = doctor_command(db_path=db_path)

            self.assertEqual(code, 0)
            output = output_buf.getvalue()
            self.assertIn("Database & State Durability", output)
            self.assertIn("journal=wal", output.lower())
            self.assertIn("integrity=OK", output)


if __name__ == "__main__":
    unittest.main()

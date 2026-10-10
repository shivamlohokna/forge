"""Background workflow execution worker using PySide6 QThread."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from forge.core.engine import Engine, EngineHook
from forge.core.events import EventType, WorkflowEvent
from forge.core.result import WorkflowResult
from forge.core.task import Task
from forge.core.workflow import Workflow
from forge.declarative.loader import load_declarative_workflow
from forge.exceptions import WorkflowSpecError
from forge.persistence.store import ExecutionStore
from forge.utils.sanitizer import sanitize, sanitize_error

logger = logging.getLogger("forge.desktop.runner")


class DesktopEngineHook(EngineHook):
    """EngineHook bridging Forge lifecycle callbacks to Qt signals."""

    def __init__(self, emitter: WorkflowRunnerSignals) -> None:
        self.emitter = emitter

    def on_task_start(self, task: Task, attempt: int) -> None:
        self.emitter.sig_task_started.emit(task.name, attempt)

    def on_task_success(self, task: Task, output: Any) -> None:
        sanitized = sanitize(output)
        summary = str(sanitized)[:200] if sanitized is not None else "Completed"
        self.emitter.sig_task_succeeded.emit(task.name, summary, getattr(task, "duration", 0.0) or 0.0)

    def on_task_failure(self, task: Task, error: Exception) -> None:
        clean_err = sanitize_error(str(error)) or "Task failed"
        self.emitter.sig_task_failed.emit(task.name, clean_err, getattr(task, "duration", 0.0) or 0.0)

    def on_task_skipped(self, task: Task) -> None:
        reason = getattr(task, "skip_reason", None) or "Condition evaluated to false"
        self.emitter.sig_task_skipped.emit(task.name, reason)


class WorkflowRunnerSignals(QObject):
    """Signals emitted across the thread boundary to update the GUI."""

    sig_started = Signal(str, str)             # run_id, workflow_name
    sig_task_ready = Signal(str)               # task_name
    sig_task_started = Signal(str, int)        # task_name, attempt
    sig_task_succeeded = Signal(str, str, float) # task_name, output_summary, duration
    sig_task_failed = Signal(str, str, float)  # task_name, error_message, duration
    sig_task_skipped = Signal(str, str)        # task_name, reason
    sig_log_emitted = Signal(str, str)         # level, sanitized_message
    sig_finished = Signal(bool, str, float, dict) # success, run_id, duration, summary
    sig_error = Signal(str)                    # pre-flight or unhandled error


class WorkflowRunnerThread(QThread):
    """Executes a Forge workflow in a separate background thread."""

    def __init__(
        self,
        workflow_spec_or_path: dict[str, Any] | str | Path,
        runtime_parameters: dict[str, Any] | None = None,
        max_workers: int = 4,
        db_path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if isinstance(workflow_spec_or_path, dict):
            wf_copy = dict(workflow_spec_or_path)
            norm_tasks = []
            for t in wf_copy.get("tasks", []):
                task = dict(t)
                tid = str(task.get("id") or task.get("name") or "task").strip()
                task["id"] = tid
                task["name"] = str(task.get("name") or tid).strip()
                params = dict(task.get("params", {}))
                for k in ["command", "working_directory", "path", "source", "destination", "content", "url", "method", "expected_status"]:
                    if k in task and k not in params:
                        params[k] = task[k]
                if "action" in task and "operation" not in params:
                    params["operation"] = str(task["action"]).lower()
                elif "operation" in task and "operation" not in params:
                    params["operation"] = str(task["operation"]).lower()
                task["params"] = params
                norm_tasks.append(task)
            wf_copy["tasks"] = norm_tasks
            self.spec_or_path = wf_copy
        else:
            self.spec_or_path = workflow_spec_or_path
        self.runtime_parameters = runtime_parameters or {}
        self.max_workers = max_workers
        self.db_path = db_path
        self.signals = WorkflowRunnerSignals()
        self._engine: Engine | None = None
        self._is_cancelled: bool = False

    def cancel(self) -> None:
        """Request cooperative cancellation of the running workflow."""
        self._is_cancelled = True
        if self._engine:
            self._engine.cancel()
        self.signals.sig_log_emitted.emit("WARN", "Cancellation requested by user.")

    def run(self) -> None:
        """Worker thread entry point."""
        start_time = time.perf_counter()
        try:
            # 1. Load and parse declarative workflow
            self.signals.sig_log_emitted.emit("INFO", "Validating workflow DAG structure...")
            try:
                workflow: Workflow = load_declarative_workflow(
                    self.spec_or_path,
                    parameters=self.runtime_parameters,
                )
            except WorkflowSpecError as err:
                self.signals.sig_error.emit(f"Workflow Validation Error: {err}")
                self.signals.sig_log_emitted.emit("ERROR", f"Validation failed: {err}")
                return
            except Exception as err:
                self.signals.sig_error.emit(f"Failed to load workflow: {err}")
                self.signals.sig_log_emitted.emit("ERROR", f"Load error: {err}")
                return

            # 2. Persistence store setup
            store: ExecutionStore | None = None
            if self.db_path:
                try:
                    store = ExecutionStore.create(self.db_path)
                except Exception as db_err:
                    self.signals.sig_log_emitted.emit("WARN", f"Could not open persistence DB: {db_err}")

            # 3. Create engine with hook and event subscriptions
            hook = DesktopEngineHook(self.signals)
            self._engine = Engine(
                max_workers=self.max_workers,
                hooks=[hook],
                store=store,
                verbose=False,
            )

            # Subscribe to events for fine-grained logging
            def on_event(ev: WorkflowEvent) -> None:
                if ev.event_type == EventType.WORKFLOW_STARTED:
                    self.signals.sig_started.emit(ev.run_id or "", ev.workflow_name)
                    self.signals.sig_log_emitted.emit("INFO", f"Workflow '{ev.workflow_name}' started.")
                elif ev.event_type == EventType.TASK_READY and ev.task_name:
                    self.signals.sig_task_ready.emit(ev.task_name)
                elif ev.event_type == EventType.WORKFLOW_FINISHED:
                    self.signals.sig_log_emitted.emit("INFO", f"Workflow finished with status: {ev.data.get('status')}")

            self._engine.events.subscribe(on_event)

            # 4. Execute workflow
            result: WorkflowResult = self._engine.run(workflow, parameters=self.runtime_parameters)
            elapsed = time.perf_counter() - start_time

            summary = {
                "run_id": result.run_id,
                "status": result.status.value,
                "total_tasks": result.total_tasks,
                "successful_tasks": len(result.successful_tasks),
                "failed_tasks": len(result.failed_tasks),
                "skipped_tasks": len(result.skipped_tasks),
                "cancelled_tasks": len(result.cancelled_tasks),
                "duration_seconds": elapsed,
            }

            self.signals.sig_finished.emit(
                result.is_success,
                result.run_id,
                elapsed,
                summary,
            )

        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            self.signals.sig_error.emit(f"Execution terminated with error: {exc}")
            self.signals.sig_log_emitted.emit("ERROR", f"Fatal execution exception: {exc}")
        finally:
            if store is not None:
                store.close()

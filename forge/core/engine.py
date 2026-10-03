"""Execution Engine for Forge V2 workflows.

This module provides the central execution brain responsible for validating
workflows, resolving topological dependencies, scheduling tasks across
executors (sequential or parallel thread pool), enforcing retries and timeouts,
handling failure strategies, managing cancellation, and recording audit telemetry.

Persistence (optional)
──────────────────────
Pass an :class:`~forge.persistence.ExecutionStore` as ``store=`` to have the
Engine durably record every workflow run, task run, and individual attempt.  The
Engine never imports SQL or knows the underlying storage technology — it only
calls the store's repository API.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Callable

from .events import EventDispatcher, EventType, WorkflowEvent
from .executor import SequentialExecutor, TaskExecutor, ThreadPoolTaskExecutor
from .result import (
    TaskAttempt,
    TaskResult,
    WorkflowResult,
    WorkflowStatus,
)
from .task import (
    ExecutionContext,
    FailureStrategy,
    Task,
    TaskStatus,
)
from .workflow import Workflow
from ..exceptions import (
    CircularDependencyError,
    MissingDependencyError,
    TaskTimeoutError,
)

if TYPE_CHECKING:
    # Import only for type hints — avoids a hard runtime dependency from
    # core → persistence that would create a circular import risk.
    from ..persistence.store import ExecutionStore

logger = logging.getLogger("forge.engine")


class EngineHook:
    """Base callback interface for intercepting workflow and task lifecycle events."""

    def on_workflow_start(self, workflow: Workflow) -> None:
        pass

    def on_task_start(self, task: Task, attempt: int) -> None:
        pass

    def on_task_success(self, task: Task, output: Any) -> None:
        pass

    def on_task_retry(self, task: Task, attempt: int, delay: float, error: Exception) -> None:
        pass

    def on_task_failure(self, task: Task, error: Exception) -> None:
        pass

    def on_task_skipped(self, task: Task) -> None:
        pass

    def on_task_blocked(self, task: Task, blocking_dep: Task) -> None:
        pass

    def on_task_cancelled(self, task: Task) -> None:
        pass

    def on_workflow_finish(self, workflow: Workflow, result: WorkflowResult) -> None:
        pass


class ConsoleLoggingHook(EngineHook):
    """Default logger hook outputting clean, informative execution messages."""

    def on_workflow_start(self, workflow: Workflow) -> None:
        print(f"\n[Forge] Starting workflow: '{workflow.name}' (id: {workflow.workflow_id})")
        print(f"[Forge] Registered tasks: {len(workflow.tasks)}")

    def on_task_start(self, task: Task, attempt: int) -> None:
        suffix = f" (Attempt {attempt})" if attempt > 1 else ""
        print(f"  -> [RUNNING]  Task: '{task.name}' (id: {task.task_id}){suffix}")

    def on_task_success(self, task: Task, output: Any) -> None:
        print(f"  v  [SUCCESS]  Task: '{task.name}'")

    def on_task_retry(self, task: Task, attempt: int, delay: float, error: Exception) -> None:
        print(
            f"  !  [RETRY]    Task: '{task.name}' failed: {error}. "
            f"Retrying in {delay:.2f}s..."
        )

    def on_task_failure(self, task: Task, error: Exception) -> None:
        print(f"  x  [FAILED]   Task: '{task.name}': {error}")

    def on_task_skipped(self, task: Task) -> None:
        print(f"  -  [SKIPPED]  Task: '{task.name}'")

    def on_task_blocked(self, task: Task, blocking_dep: Task) -> None:
        print(
            f"  o  [BLOCKED]  Task: '{task.name}' (dependency '{blocking_dep.name}' was not successful)"
        )

    def on_task_cancelled(self, task: Task) -> None:
        print(f"  /  [CANCELLED] Task: '{task.name}'")

    def on_workflow_finish(self, workflow: Workflow, result: WorkflowResult) -> None:
        status_symbol = "SUCCESS" if result.is_success else result.status.value
        print(f"[Forge] Workflow '{workflow.name}' finished: {status_symbol} ({result.duration_seconds:.2f}s)\n")


class Engine:
    """The brain of Forge responsible for executing workflows according to policy.

    Args:
        verbose:    If True (default) the ConsoleLoggingHook is attached.
        max_workers: Number of parallel worker threads.  ``1`` means sequential.
        executor:   Custom :class:`TaskExecutor` implementation.
        hooks:      Additional lifecycle hook listeners.
        store:      Optional :class:`~forge.persistence.ExecutionStore`.  When
                    provided every run is durably persisted.  When omitted the
                    Engine behaves exactly as before (no persistence).
    """

    def __init__(
        self,
        verbose: bool = True,
        max_workers: int = 1,
        executor: TaskExecutor | None = None,
        hooks: list[EngineHook] | None = None,
        store: ExecutionStore | None = None,
    ) -> None:
        self.hooks: list[EngineHook] = hooks or []
        if verbose:
            self.hooks.append(ConsoleLoggingHook())

        self.events: EventDispatcher = EventDispatcher()
        self.max_workers: int = max_workers
        self.executor: TaskExecutor = executor or (
            SequentialExecutor() if max_workers <= 1 else ThreadPoolTaskExecutor(max_workers=max_workers)
        )
        self._cancel_requested: bool = False
        self._lock: threading.Lock = threading.Lock()
        # Persistence — None means disabled (backwards-compatible default)
        self._store: ExecutionStore | None = store

    def add_hook(self, hook: EngineHook) -> None:
        """Register a new lifecycle hook listener."""
        self.hooks.append(hook)

    def cancel(self) -> None:
        """Signal the engine to cancel pending workflow tasks."""
        self._cancel_requested = True

    def _notify(self, method_name: str, *args: Any) -> None:
        """Dispatch lifecycle events to all registered hooks."""
        for hook in self.hooks:
            method = getattr(hook, method_name, None)
            if callable(method):
                try:
                    method(*args)
                except Exception as hook_err:
                    logger.warning(f"Hook '{hook.__class__.__name__}.{method_name}' raised: {hook_err}")

    def _emit_event(
        self,
        event_type: EventType,
        workflow: Workflow,
        task: Task | None = None,
        attempt: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured event through the pub/sub dispatcher."""
        event = WorkflowEvent(
            event_type=event_type,
            workflow_id=workflow.workflow_id,
            workflow_name=workflow.name,
            task_id=task.task_id if task else None,
            task_name=task.name if task else None,
            attempt=attempt,
            data=data or {},
        )
        self.events.emit(event)

    def run(
        self,
        workflow: Workflow,
        parameters: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Execute a workflow through its DAG lifecycle.

        Args:
            workflow: The Workflow DAG to execute.
            parameters: Runtime parameters overriding or extending workflow defaults.

        Returns:
            WorkflowResult: Full execution telemetry and task results.
        """
        self._cancel_requested = False
        combined_params = {**workflow.parameters, **(parameters or {})}
        workflow_result = WorkflowResult(
            workflow_id=workflow.workflow_id,
            workflow_name=workflow.name,
            parameters=combined_params,
            metadata=workflow.metadata,
        )

        workflow.reset()
        workflow.status = WorkflowStatus.RUNNING
        self._notify("on_workflow_start", workflow)
        self._emit_event(EventType.WORKFLOW_STARTED, workflow)

        # Persist the workflow run row immediately so it exists even if the
        # process dies mid-execution.  Store is optional — no-op when None.
        if self._store is not None:
            try:
                self._store.create_workflow_run(
                    run_id=workflow_result.run_id,
                    workflow_id=workflow_result.workflow_id,
                    workflow_name=workflow_result.workflow_name,
                    status=WorkflowStatus.RUNNING.value,
                    started_at=workflow_result.start_time.isoformat(),
                    parameters=combined_params,
                    metadata=workflow.metadata,
                )
            except Exception as store_err:
                logger.warning("Persistence: failed to create workflow run: %s", store_err)


        # 1. Graph validation & topological batching
        try:
            batches = workflow.get_execution_batches()
        except (CircularDependencyError, MissingDependencyError) as dag_err:
            logger.error(f"Workflow pre-flight validation failed: {dag_err}")
            workflow.status = WorkflowStatus.FAILED
            workflow_result.finish(WorkflowStatus.FAILED)
            self._notify("on_workflow_finish", workflow, workflow_result)
            self._emit_event(EventType.WORKFLOW_FINISHED, workflow, data={"status": "FAILED", "error": str(dag_err)})
            self._persist_complete(workflow_result)
            return workflow_result

        all_tasks = [t for batch in batches for t in batch]
        upstream_outputs: dict[str, Any] = {}
        structured_outputs: dict[str, dict[str, Any]] = {}


        # 2. Iterate through topological batches (tasks within a batch are independent)
        for batch_idx, batch in enumerate(batches):
            # Check for cancellation before starting the batch
            if self._cancel_requested:
                self._cancel_remaining_tasks(batches[batch_idx:], workflow_result, workflow)
                workflow.status = WorkflowStatus.CANCELLED
                workflow_result.finish(WorkflowStatus.CANCELLED)
                self._notify("on_workflow_finish", workflow, workflow_result)
                self._emit_event(EventType.WORKFLOW_FINISHED, workflow, data={"status": "CANCELLED"})
                self._persist_complete(workflow_result)
                return workflow_result

            # Evaluate dependencies within the batch
            ready_tasks: list[Task] = []
            for task in batch:
                blocking_dep = self._get_blocking_dependency(task)
                if blocking_dep is not None:
                    task.status = TaskStatus.BLOCKED
                    task_res = TaskResult(
                        task_id=task.task_id,
                        task_name=task.name,
                        status=TaskStatus.BLOCKED,
                        run_id=workflow_result.run_id,
                        error_message=(
                            f"Blocked because prerequisite task '{blocking_dep.name}' "
                            f"(status: {blocking_dep.status.value}) was not successful."
                        ),
                    )
                    workflow_result.add_task_result(task_res)
                    self._notify("on_task_blocked", task, blocking_dep)
                    self._emit_event(EventType.TASK_BLOCKED, workflow, task=task, data={"blocking_dependency": blocking_dep.name})
                else:
                    ready_tasks.append(task)
                    self._emit_event(EventType.TASK_READY, workflow, task=task)

            if not ready_tasks:
                continue

            # Execute ready tasks (either sequentially or concurrently via executor)
            batch_results = self._execute_batch(
                ready_tasks=ready_tasks,
                workflow=workflow,
                parameters=combined_params,
                upstream_outputs=upstream_outputs,
                structured_outputs=structured_outputs,
                run_id=workflow_result.run_id,
            )

            # Process completed batch results
            halt_workflow = False
            for task, task_res in batch_results:
                workflow_result.add_task_result(task_res)
                self._persist_task_result(workflow_result.run_id, task_res)

                if task.status == TaskStatus.SUCCESS:
                    from forge.core.output import get_structured_output
                    struct_out = get_structured_output(task_res.output)
                    with self._lock:
                        upstream_outputs[task.task_id] = task_res.output
                        upstream_outputs[task.name] = task_res.output
                        structured_outputs[task.task_id] = struct_out
                        structured_outputs[task.name] = struct_out
                elif task.status == TaskStatus.FAILED:
                    if task.failure_strategy in (FailureStrategy.STOP, FailureStrategy.RETRY):
                        halt_workflow = True


            if halt_workflow:
                self._cascade_blocked_to_unexecuted(all_tasks, workflow_result)
                workflow.status = WorkflowStatus.FAILED
                workflow_result.finish(WorkflowStatus.FAILED)
                self._notify("on_workflow_finish", workflow, workflow_result)
                self._emit_event(EventType.WORKFLOW_FINISHED, workflow, data={"status": "FAILED"})
                self._persist_complete(workflow_result)
                return workflow_result

        # 3. Finalize workflow status
        final_status = self._determine_final_workflow_status(workflow_result)
        workflow.status = final_status
        workflow_result.finish(final_status)
        self._notify("on_workflow_finish", workflow, workflow_result)
        self._emit_event(EventType.WORKFLOW_FINISHED, workflow, data={"status": final_status.value})
        self._persist_complete(workflow_result)

        return workflow_result

    def _execute_batch(
        self,
        ready_tasks: list[Task],
        workflow: Workflow,
        parameters: dict[str, Any],
        upstream_outputs: dict[str, Any],
        structured_outputs: dict[str, dict[str, Any]] | None = None,
        run_id: str | None = None,
    ) -> list[tuple[Task, TaskResult]]:
        """Execute a batch of ready independent tasks."""
        if len(ready_tasks) == 1 or self.max_workers <= 1:
            # Single task or sequential mode: run directly
            results = []
            for task in ready_tasks:
                if self._cancel_requested:
                    task.status = TaskStatus.CANCELLED
                    task_res = TaskResult(
                        task_id=task.task_id,
                        task_name=task.name,
                        status=TaskStatus.CANCELLED,
                        run_id=run_id,
                    )
                    self._notify("on_task_cancelled", task)
                    self._emit_event(EventType.TASK_CANCELLED, workflow, task=task)
                    results.append((task, task_res))
                    continue

                res = self._execute_task_with_retries(
                    task=task,
                    workflow=workflow,
                    parameters=parameters,
                    upstream_outputs=upstream_outputs,
                    structured_outputs=structured_outputs,
                    run_id=run_id,
                )
                results.append((task, res))
            return results

        # Concurrent parallel batch execution
        results = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(ready_tasks))) as batch_pool:
            futures = {
                batch_pool.submit(
                    self._execute_task_with_retries,
                    task,
                    workflow,
                    parameters,
                    upstream_outputs,
                    structured_outputs,
                    run_id,
                ): task
                for task in ready_tasks
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    res = future.result()
                    results.append((task, res))
                except Exception as exc:
                    task.status = TaskStatus.FAILED
                    task_res = TaskResult(
                        task_id=task.task_id,
                        task_name=task.name,
                        status=TaskStatus.FAILED,
                        error_message=str(exc),
                        run_id=run_id,
                    )
                    results.append((task, task_res))

        return results

    def _get_blocking_dependency(self, task: Task) -> Task | None:
        """Return the first upstream dependency that is not SUCCESS, or None."""
        for dep in task.dependencies:
            if dep.status != TaskStatus.SUCCESS:
                return dep
        return None

    def _execute_task_with_retries(
        self,
        task: Task,
        workflow: Workflow,
        parameters: dict[str, Any],
        upstream_outputs: dict[str, Any],
        structured_outputs: dict[str, dict[str, Any]] | None = None,
        run_id: str | None = None,
    ) -> TaskResult:
        """Run a single task handling execution, timeouts, retries, and failure strategies."""
        task_res = TaskResult(task_id=task.task_id, task_name=task.name, run_id=run_id)

        max_attempts = task.max_retries + 1 if task.failure_strategy == FailureStrategy.RETRY else 1

        for attempt in range(1, max_attempts + 1):
            if self._cancel_requested:
                task.status = TaskStatus.CANCELLED
                task_res.status = TaskStatus.CANCELLED
                self._notify("on_task_cancelled", task)
                self._emit_event(EventType.TASK_CANCELLED, workflow, task=task)
                return task_res

            task.attempts = attempt
            task.status = TaskStatus.RUNNING
            self._notify("on_task_start", task, attempt)
            self._emit_event(EventType.TASK_STARTED, workflow, task=task, attempt=attempt)
            self._emit_event(EventType.TASK_ATTEMPT_STARTED, workflow, task=task, attempt=attempt)

            attempt_rec = TaskAttempt(attempt_number=attempt, status=TaskStatus.RUNNING)

            # Build execution context
            with self._lock:
                task_upstream_results = {}
                for dep in task.dependencies:
                    dep_output = upstream_outputs.get(dep.task_id)
                    task_upstream_results[dep.task_id] = dep_output
                    task_upstream_results[dep.name] = dep_output
                current_outputs = dict(structured_outputs or {})

            context = ExecutionContext(
                task_id=task.task_id,
                task_name=task.name,
                workflow_id=workflow.workflow_id,
                workflow_name=workflow.name,
                attempt=attempt,
                parameters=parameters,
                upstream_results=task_upstream_results,
                outputs=current_outputs,
            )

            # Dynamically resolve any template references in task parameters using runtime outputs
            try:
                task.resolve_template_attributes(context)
            except Exception as res_err:
                error_tb = "".join(
                    traceback.format_exception(type(res_err), res_err, res_err.__traceback__)
                )
                attempt_rec.finish(
                    status=TaskStatus.FAILED,
                    error_message=str(res_err),
                    error_traceback=error_tb,
                )
                task_res.add_attempt(attempt_rec)
                task.status = TaskStatus.FAILED
                task_res.status = TaskStatus.FAILED
                self._notify("on_task_failure", task, res_err)
                self._emit_event(EventType.TASK_FAILED, workflow, task=task, data={"error": str(res_err)})
                return task_res


            # Run task with optional timeout
            output, error = self._run_with_timeout(task, context)

            if error is None:
                # Succeeded!
                task.status = TaskStatus.SUCCESS
                task.result = output
                task.last_error = None
                attempt_rec.finish(status=TaskStatus.SUCCESS, output=output)
                task_res.add_attempt(attempt_rec)
                self._notify("on_task_success", task, output)
                self._emit_event(EventType.TASK_ATTEMPT_FINISHED, workflow, task=task, attempt=attempt, data={"status": "SUCCESS"})
                self._emit_event(EventType.TASK_SUCCEEDED, workflow, task=task, data={"output": str(output)[:100]})
                return task_res

            # Failed attempt
            task.last_error = error
            error_tb = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
            attempt_rec.finish(
                status=TaskStatus.FAILED,
                error_message=str(error),
                error_traceback=error_tb,
            )
            task_res.add_attempt(attempt_rec)
            self._emit_event(EventType.TASK_ATTEMPT_FINISHED, workflow, task=task, attempt=attempt, data={"status": "FAILED", "error": str(error)})

            # Evaluate retry
            if task.failure_strategy == FailureStrategy.RETRY and attempt < max_attempts:
                delay = task.retry_policy.get_delay_for_attempt(attempt)
                self._notify("on_task_retry", task, attempt, delay, error)
                if delay > 0:
                    time.sleep(delay)
                continue

            # No more retries; apply failure strategy
            if task.failure_strategy == FailureStrategy.SKIP:
                task.status = TaskStatus.SKIPPED
                task_res.status = TaskStatus.SKIPPED
                self._notify("on_task_skipped", task)
                self._emit_event(EventType.TASK_SKIPPED, workflow, task=task)
                return task_res
            else:
                task.status = TaskStatus.FAILED
                task_res.status = TaskStatus.FAILED
                self._notify("on_task_failure", task, error)
                self._emit_event(EventType.TASK_FAILED, workflow, task=task, data={"error": str(error)})
                return task_res

        return task_res

    def _run_with_timeout(
        self,
        task: Task,
        context: ExecutionContext,
    ) -> tuple[Any, Exception | None]:
        """Execute task.run(context) with non-blocking timeout enforcement."""
        if task.timeout is None or task.timeout <= 0:
            try:
                output = task.run(context)
                return output, None
            except Exception as exc:
                return None, exc

        # Execute inside thread pool with timeout without blocking on exit
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(task.run, context)
            output = future.result(timeout=task.timeout)
            executor.shutdown(wait=False)
            return output, None
        except Exception as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            if "Timeout" in exc.__class__.__name__:
                return None, TaskTimeoutError(
                    f"Task '{task.name}' timed out after {task.timeout:.2f}s"
                )
            return None, exc

    def _cancel_remaining_tasks(
        self,
        remaining_batches: list[list[Task]],
        workflow_result: WorkflowResult,
        workflow: Workflow,
    ) -> None:
        """Mark remaining tasks as CANCELLED."""
        for batch in remaining_batches:
            for task in batch:
                if task.task_id not in workflow_result.task_results:
                    task.status = TaskStatus.CANCELLED
                    task_res = TaskResult(
                        task_id=task.task_id,
                        task_name=task.name,
                        status=TaskStatus.CANCELLED,
                        run_id=workflow_result.run_id,
                        error_message="Workflow execution was cancelled.",
                    )
                    workflow_result.add_task_result(task_res)
                    self._notify("on_task_cancelled", task)
                    self._emit_event(EventType.TASK_CANCELLED, workflow, task=task)

    def _cascade_blocked_to_unexecuted(
        self,
        all_tasks: list[Task],
        workflow_result: WorkflowResult,
    ) -> None:
        """Mark remaining unexecuted tasks as BLOCKED when workflow halts."""
        executed_ids = set(workflow_result.task_results.keys())
        for task in all_tasks:
            if task.task_id not in executed_ids:
                task.status = TaskStatus.BLOCKED
                task_res = TaskResult(
                    task_id=task.task_id,
                    task_name=task.name,
                    status=TaskStatus.BLOCKED,
                    run_id=workflow_result.run_id,
                    error_message="Workflow halted due to upstream failure.",
                )
                workflow_result.add_task_result(task_res)

    def _determine_final_workflow_status(
        self,
        result: WorkflowResult,
    ) -> WorkflowStatus:
        """Determine overall workflow status based on aggregated task results."""
        if not result.task_results:
            return WorkflowStatus.SUCCESS

        has_cancelled = any(r.is_cancelled for r in result.task_results.values())
        has_failed = any(r.is_failed for r in result.task_results.values())
        has_blocked = any(r.is_blocked for r in result.task_results.values())
        has_success = any(r.is_success for r in result.task_results.values())

        if has_cancelled:
            return WorkflowStatus.CANCELLED
        elif not has_failed and not has_blocked:
            return WorkflowStatus.SUCCESS
        elif has_success and (has_failed or has_blocked):
            return WorkflowStatus.PARTIAL_SUCCESS
        else:
            return WorkflowStatus.FAILED

    # ── Persistence helpers ───────────────────────────────────────────────────
    # These methods are the only place the Engine talks to the store.
    # They are deliberately fire-and-forget with exception swallowing so
    # a persistence failure never kills an otherwise successful workflow.

    def _persist_task_result(
        self,
        run_id: str,
        task_res: TaskResult,
    ) -> None:
        """Persist a completed TaskResult (and its attempts) to the store."""
        if self._store is None:
            return
        try:
            task_run_id = f"{run_id}:{task_res.task_id}"
            self._store.save_task_run(
                run_id=run_id,
                task_run_id=task_run_id,
                task_name=task_res.task_name,
                status=task_res.status.value,
                started_at=task_res.start_time.isoformat() if task_res.start_time else None,
                finished_at=task_res.end_time.isoformat() if task_res.end_time else None,
                duration_seconds=task_res.duration_seconds,
                attempt_count=task_res.attempt_count,
                output=task_res.output,
                error_message=task_res.error_message,
                error_traceback=task_res.error_traceback,
            )
            for attempt in task_res.attempts:
                self._store.save_task_attempt(
                    task_run_id=task_run_id,
                    attempt_number=attempt.attempt_number,
                    status=attempt.status.value,
                    started_at=attempt.start_time.isoformat(),
                    finished_at=attempt.end_time.isoformat() if attempt.end_time else None,
                    duration_seconds=attempt.duration_seconds,
                    output=attempt.output,
                    error_message=attempt.error_message,
                    error_traceback=attempt.error_traceback,
                )
        except Exception as store_err:
            logger.warning("Persistence: failed to save task run '%s': %s", task_res.task_name, store_err)

    def _persist_complete(self, workflow_result: WorkflowResult) -> None:
        """Update the workflow run row with the final status and counters.

        Also persists any task results that haven't been persisted yet
        (e.g. BLOCKED tasks that are added after execution halts).
        """
        if self._store is None:
            return
        try:
            # Persist any task results not yet saved (BLOCKED / CANCELLED added
            # after halt — they have no attempt records)
            for task_res in workflow_result.task_results.values():
                if not task_res.attempts:
                    task_run_id = f"{workflow_result.run_id}:{task_res.task_id}"
                    # No attempts means the task never ran — persist the row only
                    self._store.save_task_run(
                        run_id=workflow_result.run_id,
                        task_run_id=task_run_id,
                        task_name=task_res.task_name,
                        status=task_res.status.value,
                        started_at=None,
                        finished_at=None,
                        duration_seconds=None,
                        attempt_count=0,
                        output=None,
                        error_message=task_res.error_message,
                        error_traceback=None,
                    )

            self._store.complete_workflow_run(
                run_id=workflow_result.run_id,
                status=workflow_result.status.value,
                finished_at=(
                    workflow_result.end_time.isoformat()
                    if workflow_result.end_time else None
                ),
                duration_seconds=workflow_result.duration_seconds,
                total_tasks=workflow_result.total_tasks,
                success_count=len(workflow_result.successful_tasks),
                failed_count=len(workflow_result.failed_tasks),
                skipped_count=len(workflow_result.skipped_tasks),
                blocked_count=len(workflow_result.blocked_tasks),
                cancelled_count=len(workflow_result.cancelled_tasks),
            )
        except Exception as store_err:
            logger.warning("Persistence: failed to complete workflow run: %s", store_err)


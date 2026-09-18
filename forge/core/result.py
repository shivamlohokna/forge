"""Execution result models and telemetry for Forge V2.

This module provides data models for capturing task attempts, task-level
aggregate results, and full workflow execution summaries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .task import TaskStatus



class WorkflowStatus(str, Enum):
    """Execution states for a workflow."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        """Return True if the workflow has reached a terminal state."""
        return self in (
            WorkflowStatus.SUCCESS,
            WorkflowStatus.FAILED,
            WorkflowStatus.PARTIAL_SUCCESS,
            WorkflowStatus.ABORTED,
            WorkflowStatus.CANCELLED,
        )



@dataclass
class TaskAttempt:
    """Telemetry recorded for an individual attempt of a task."""

    attempt_number: int
    status: TaskStatus
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    output: Any = None
    error_message: str | None = None
    error_traceback: str | None = None

    def finish(
        self,
        status: TaskStatus,
        output: Any = None,
        error_message: str | None = None,
        error_traceback: str | None = None,
    ) -> None:
        """Mark this attempt as finished and record duration."""
        self.status = status
        self.end_time = datetime.now(timezone.utc)
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()
        self.output = output
        self.error_message = error_message
        self.error_traceback = error_traceback

    def to_dict(self) -> dict[str, Any]:
        """Convert attempt details to a serializable dictionary."""
        return {
            "attempt_number": self.attempt_number,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "output": self.output,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
        }


@dataclass
class TaskResult:
    """Consolidated outcome of a task execution across all its attempts."""

    task_id: str
    task_name: str
    status: TaskStatus = TaskStatus.PENDING
    attempts: list[TaskAttempt] = field(default_factory=list)
    output: Any = None
    error_message: str | None = None
    error_traceback: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    run_id: str | None = None

    @property
    def attempt_count(self) -> int:
        """Total number of execution attempts made."""
        return len(self.attempts)

    @property
    def is_success(self) -> bool:
        """Return True if the task successfully completed."""
        return self.status == TaskStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        """Return True if the task ended in a failed state."""
        return self.status == TaskStatus.FAILED

    @property
    def is_blocked(self) -> bool:
        """Return True if the task was blocked by failed dependencies."""
        return self.status == TaskStatus.BLOCKED

    @property
    def is_skipped(self) -> bool:
        """Return True if the task was skipped."""
        return self.status == TaskStatus.SKIPPED

    @property
    def is_cancelled(self) -> bool:
        """Return True if the task was cancelled."""
        return self.status == TaskStatus.CANCELLED


    def add_attempt(self, attempt: TaskAttempt) -> None:
        """Add an attempt record and sync the aggregate state."""
        self.attempts.append(attempt)
        self.status = attempt.status
        self.output = attempt.output
        self.error_message = attempt.error_message
        self.error_traceback = attempt.error_traceback

        if self.start_time is None:
            self.start_time = attempt.start_time

        if attempt.end_time is not None:
            self.end_time = attempt.end_time
            if self.start_time:
                self.duration_seconds = (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Convert task result to a serializable dictionary."""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "run_id": self.run_id,
            "status": self.status.value,
            "attempt_count": self.attempt_count,
            "attempts": [a.to_dict() for a in self.attempts],
            "output": self.output,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
        }

    def __repr__(self) -> str:
        return (
            f"<TaskResult task_id='{self.task_id}' name='{self.task_name}' "
            f"status='{self.status.value}' attempts={self.attempt_count} "
            f"duration={self.duration_seconds:.2f}s>"
        )


@dataclass
class WorkflowResult:
    """Comprehensive summary of an entire workflow execution run."""

    workflow_id: str
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    task_results: dict[str, TaskResult] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")


    def add_task_result(self, result: TaskResult) -> None:
        """Register a completed task result."""
        self.task_results[result.task_id] = result

    def get_task_result(self, task_id_or_name: str) -> TaskResult | None:
        """Look up a task result by either task_id or task_name."""
        if task_id_or_name in self.task_results:
            return self.task_results[task_id_or_name]
        for result in self.task_results.values():
            if result.task_name == task_id_or_name:
                return result
        return None

    def finish(self, status: WorkflowStatus) -> None:
        """Mark the workflow run as finished and compute total duration."""
        self.status = status
        self.end_time = datetime.now(timezone.utc)
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()

    @property
    def is_terminal(self) -> bool:
        """Return True if the workflow execution has finished."""
        return self.status.is_terminal

    @property
    def is_success(self) -> bool:
        """Return True if the workflow completed with SUCCESS."""
        return self.status == WorkflowStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        """Return True if the workflow ended in FAILED or ABORTED."""
        return self.status in (WorkflowStatus.FAILED, WorkflowStatus.ABORTED)


    @property
    def total_tasks(self) -> int:
        """Total number of tasks in this run."""
        return len(self.task_results)

    @property
    def successful_tasks(self) -> list[TaskResult]:
        """Tasks that executed successfully."""
        return [r for r in self.task_results.values() if r.is_success]

    @property
    def failed_tasks(self) -> list[TaskResult]:
        """Tasks that failed."""
        return [r for r in self.task_results.values() if r.is_failed]

    @property
    def skipped_tasks(self) -> list[TaskResult]:
        """Tasks that were skipped."""
        return [r for r in self.task_results.values() if r.is_skipped]

    @property
    def blocked_tasks(self) -> list[TaskResult]:
        """Tasks that were blocked due to upstream dependency failures."""
        return [r for r in self.task_results.values() if r.is_blocked]

    @property
    def cancelled_tasks(self) -> list[TaskResult]:
        """Tasks that were cancelled."""
        return [r for r in self.task_results.values() if r.is_cancelled]


    def to_dict(self) -> dict[str, Any]:
        """Convert entire workflow result to a JSON-serializable dictionary."""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total_tasks": self.total_tasks,
            "successful_count": len(self.successful_tasks),
            "failed_count": len(self.failed_tasks),
            "skipped_count": len(self.skipped_tasks),
            "blocked_count": len(self.blocked_tasks),
            "parameters": self.parameters,
            "metadata": self.metadata,
            "task_results": {k: v.to_dict() for k, v in self.task_results.items()},
        }

    def summary(self) -> str:
        """Generate a human-readable execution report."""
        lines = [
            f"=== Workflow Execution Summary: {self.workflow_name} ===",
            f"Run ID:    {self.run_id}",
            f"Workflow:  {self.workflow_name} (id: {self.workflow_id})",
            f"Status:    {self.status.value}",
            f"Duration:  {self.duration_seconds:.2f}s",
            f"Tasks:     {self.total_tasks} total "
            f"({len(self.successful_tasks)} succeeded, "
            f"{len(self.failed_tasks)} failed, "
            f"{len(self.blocked_tasks)} blocked, "
            f"{len(self.skipped_tasks)} skipped)",
            "-------------------------------------------------------",
        ]
        for tr in self.task_results.values():
            status_tag = f"[{tr.status.value}]"
            err_note = f" (Error: {tr.error_message})" if tr.error_message else ""
            lines.append(
                f"  {status_tag:<11} {tr.task_name} "
                f"(id: {tr.task_id}, attempts: {tr.attempt_count}, {tr.duration_seconds:.2f}s){err_note}"
            )
        lines.append("=======================================================")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<WorkflowResult run_id='{self.run_id}' workflow_id='{self.workflow_id}' "
            f"name='{self.workflow_name}' status='{self.status.value}' "
            f"tasks={self.total_tasks} duration={self.duration_seconds:.2f}s>"
        )


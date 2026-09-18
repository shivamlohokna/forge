"""Core Task abstraction and execution contracts for Forge V2.

This module defines the foundational Task contract, status enums,
failure handling strategies, and runtime execution context.
"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Execution states for a task."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        """Return True if the task has reached a completed or terminal state."""
        return self in (
            TaskStatus.SUCCESS,
            TaskStatus.FAILED,
            TaskStatus.SKIPPED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        )


    @property
    def is_successful(self) -> bool:
        """Return True if the task finished successfully."""
        return self == TaskStatus.SUCCESS


class FailureStrategy(str, Enum):
    """Policies dictating engine behavior when a task execution fails."""

    STOP = "STOP"          # Halt the workflow immediately (fail-fast)
    RETRY = "RETRY"        # Retry execution up to max_retries before failing
    SKIP = "SKIP"          # Mark task as SKIPPED and proceed with remaining tasks
    CONTINUE = "CONTINUE"  # Mark task as FAILED but continue executing independent tasks


@dataclass
class RetryPolicy:
    """Configures retry behavior for a task."""

    max_retries: int = 0
    delay: float = 0.0
    backoff_factor: float = 1.0

    def get_delay_for_attempt(self, attempt: int) -> float:
        """Calculate the backoff delay (in seconds) for a given attempt index."""
        if attempt <= 1:
            return self.delay
        return self.delay * (self.backoff_factor ** (attempt - 1))


@dataclass
class ExecutionContext:
    """Runtime context and metadata passed to tasks during execution."""

    task_id: str
    task_name: str
    workflow_id: str | None = None
    workflow_name: str | None = None
    attempt: int = 1
    parameters: dict[str, Any] = field(default_factory=dict)
    upstream_results: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_param(self, key: str, default: Any = None) -> Any:
        """Safely fetch a runtime workflow parameter."""
        return self.parameters.get(key, default)

    def get_upstream_result(self, task_id_or_name: str, default: Any = None) -> Any:
        """Fetch the output produced by an upstream task."""
        return self.upstream_results.get(task_id_or_name, default)


def _slugify(value: str) -> str:
    """Convert string into a clean URL/identifier-friendly slug."""
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "_", value)


class Task(ABC):
    """Abstract Base Class defining the contract for all Forge tasks.

    The Engine interacts strictly with this contract: it validates dependencies,
    manages lifecycle states, evaluates retries, and delegates execution via
    the `execute` method without needing to know implementation details.
    """

    def __init__(
        self,
        name: str,
        task_id: str | None = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        retry_policy: RetryPolicy | None = None,
        failure_strategy: FailureStrategy | str = FailureStrategy.STOP,
        timeout: float | None = None,
        description: str = "",
    ) -> None:
        if not name or not name.strip():
            raise ValueError("Task name cannot be empty.")

        self.name: str = name.strip()
        self.task_id: str = task_id.strip() if task_id else f"{_slugify(self.name)}_{uuid.uuid4().hex[:8]}"
        self.description: str = description

        # Dependencies
        self.dependencies: set[Task] = set()

        # Retry configuration
        if retry_policy is not None:
            self.retry_policy = retry_policy
        else:
            self.retry_policy = RetryPolicy(max_retries=max_retries, delay=retry_delay)

        # Failure strategy
        if isinstance(failure_strategy, str):
            try:
                self.failure_strategy: FailureStrategy = FailureStrategy(failure_strategy.upper())
            except ValueError:
                valid = [s.value for s in FailureStrategy]
                raise ValueError(
                    f"Invalid failure_strategy '{failure_strategy}'. Must be one of: {valid}"
                )
        else:
            self.failure_strategy = failure_strategy

        # Execution constraints
        self.timeout: float | None = timeout

        # Runtime state
        self.status: TaskStatus = TaskStatus.PENDING
        self.attempts: int = 0
        self.last_error: Exception | None = None
        self.result: Any = None

    @property
    def max_retries(self) -> int:
        """Convenience property for accessing configured maximum retries."""
        return self.retry_policy.max_retries

    @max_retries.setter
    def max_retries(self, value: int) -> None:
        self.retry_policy.max_retries = max(0, value)

    @property
    def retry_delay(self) -> float:
        """Convenience property for accessing configured retry delay."""
        return self.retry_policy.delay

    @retry_delay.setter
    def retry_delay(self, value: float) -> None:
        self.retry_policy.delay = max(0.0, float(value))

    def add_dependency(self, task: Task) -> None:
        """Add a prerequisite task that must succeed before this task can execute."""
        if not isinstance(task, Task):
            raise TypeError(f"Dependency must be an instance of Task, got {type(task).__name__}")
        if task is self:
            raise ValueError(f"Task '{self.name}' cannot depend on itself.")
        self.dependencies.add(task)

    def add_dependencies(self, *tasks: Task) -> None:
        """Add multiple prerequisite tasks."""
        for t in tasks:
            self.add_dependency(t)

    def depends_on(self, *tasks: Task) -> Task:
        """Fluent helper to add dependencies and return self for chaining."""
        self.add_dependencies(*tasks)
        return self

    def reset(self) -> None:
        """Reset the task's execution state back to PENDING for re-runs."""
        self.status = TaskStatus.PENDING
        self.attempts = 0
        self.last_error = None
        self.result = None

    @abstractmethod
    def execute(self, context: ExecutionContext) -> Any:
        """Execute the task logic with the provided runtime context.

        Subclasses must implement this method to perform their specific work.
        Raise an exception or return a result.
        """
        pass

    def run(self, context: ExecutionContext | None = None) -> Any:
        """Unified entrypoint that invokes `execute`.

        Provided for ergonomic manual runs and compatibility with V1.
        """
        if context is None:
            context = ExecutionContext(task_id=self.task_id, task_name=self.name)
        return self.execute(context)

    # Operator support: task_a >> task_b (task_b depends on task_a)
    def __rshift__(self, other: Task | list[Task]) -> Task | list[Task]:
        """Bitwise right shift operator to express dependency: A >> B means B depends on A."""
        if isinstance(other, Task):
            other.add_dependency(self)
            return other
        elif isinstance(other, list):
            for item in other:
                if not isinstance(item, Task):
                    raise TypeError("All items in dependency list must be Task instances.")
                item.add_dependency(self)
            return other
        return NotImplemented

    # Operator support: task_b << task_a (task_b depends on task_a)
    def __lshift__(self, other: Task | list[Task]) -> Task:
        """Bitwise left shift operator: B << A means B depends on A."""
        if isinstance(other, Task):
            self.add_dependency(other)
            return self
        elif isinstance(other, list):
            for item in other:
                if not isinstance(item, Task):
                    raise TypeError("All items in dependency list must be Task instances.")
                self.add_dependency(item)
            return self
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.task_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Task):
            return self.task_id == other.task_id
        return False

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id='{self.task_id}' "
            f"name='{self.name}' status='{self.status.value}'>"
        )

"""Task executor abstractions and worker pool implementations for Forge V2.

This module establishes the concurrency and worker boundary, decoupling task
execution mechanics from workflow orchestration.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from .task import ExecutionContext, Task, TaskStatus
from ..exceptions import TaskTimeoutError


class TaskExecutor(ABC):
    """Abstract Base Class for executing Forge tasks.

    Decouples task scheduling and dependency management from the underlying
    execution engine (in-process sequential, thread pool, process pool, remote workers).
    """

    @abstractmethod
    def submit(
        self,
        task: Task,
        context: ExecutionContext,
    ) -> Future[Any]:
        """Submit a task for execution with the provided runtime context.

        Returns:
            concurrent.futures.Future: A future representing pending completion.
        """
        pass

    @abstractmethod
    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shut down worker resources."""
        pass

    def __enter__(self) -> TaskExecutor:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown(wait=True)


class SequentialExecutor(TaskExecutor):
    """Synchronous executor running tasks immediately on the caller thread.

    Useful for deterministic execution, step-by-step debugging, and resource-constrained runs.
    """

    def __init__(self) -> None:
        self._is_shutdown: bool = False

    def submit(
        self,
        task: Task,
        context: ExecutionContext,
    ) -> Future[Any]:
        if self._is_shutdown:
            raise RuntimeError("Cannot submit task to a shutdown executor.")

        future: Future[Any] = Future()
        try:
            output = task.run(context)
            future.set_result(output)
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self._is_shutdown = True


class ThreadPoolTaskExecutor(TaskExecutor):
    """Concurrent executor utilizing a thread pool for parallel task execution."""

    def __init__(self, max_workers: int = 4) -> None:
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        self.max_workers: int = max_workers
        self._pool: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="forge-worker",
        )
        self._is_shutdown: bool = False

    def submit(
        self,
        task: Task,
        context: ExecutionContext,
    ) -> Future[Any]:
        if self._is_shutdown:
            raise RuntimeError("Cannot submit task to a shutdown executor.")

        # Wrap execution with timeout if declared on task
        if task.timeout is not None and task.timeout > 0:
            return self._pool.submit(self._run_with_timeout, task, context)
        return self._pool.submit(task.run, context)

    @staticmethod
    def _run_with_timeout(task: Task, context: ExecutionContext) -> Any:
        """Run task with internal timeout enforcement."""
        # Using a dedicated single-use worker for timeout isolation
        temp_pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = temp_pool.submit(task.run, context)
            return future.result(timeout=task.timeout)
        except Exception:
            temp_pool.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            temp_pool.shutdown(wait=False)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self._is_shutdown = True
        self._pool.shutdown(wait=wait, cancel_futures=cancel_futures)

"""Workflow definition and Directed Acyclic Graph (DAG) management for Forge V2.

This module provides the Workflow abstraction responsible for managing tasks,
validating dependencies, detecting circular cycles, and computing valid
execution order.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict, deque
from typing import Any, Iterator

from .result import WorkflowStatus
from .task import Task
from ..exceptions import (
    CircularDependencyError,
    MissingDependencyError,
)


def _slugify(value: str) -> str:
    """Convert string into a clean identifier-friendly slug."""
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "_", value)


class Workflow:
    """Represents an executable workflow comprised of dependent tasks forming a DAG.

    The Workflow validates task relationships, detects dependency cycles,
    and calculates topological execution order for the Engine.
    """

    def __init__(
        self,
        name: str,
        workflow_id: str | None = None,
        description: str = "",
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("Workflow name cannot be empty.")

        self.name: str = name.strip()
        self.workflow_id: str = (
            workflow_id.strip()
            if workflow_id
            else f"{_slugify(self.name)}_{uuid.uuid4().hex[:8]}"
        )
        self.description: str = description
        self.parameters: dict[str, Any] = parameters or {}
        self.metadata: dict[str, Any] = metadata or {}
        self.status: WorkflowStatus = WorkflowStatus.PENDING

        # Internal registry: task_id -> Task
        self._tasks: dict[str, Task] = {}

    @property
    def tasks(self) -> list[Task]:
        """Return the list of all registered tasks in this workflow."""
        return list(self._tasks.values())

    def add_task(self, task: Task, auto_add_dependencies: bool = True) -> Workflow:
        """Register a task into the workflow.

        Args:
            task: The Task instance to add.
            auto_add_dependencies: If True, automatically registers any upstream
                dependencies attached to the task that are not yet registered.

        Returns:
            self for fluent chaining.
        """
        if not isinstance(task, Task):
            raise TypeError(f"Expected Task instance, got {type(task).__name__}")

        if task.task_id in self._tasks and self._tasks[task.task_id] is not task:
            raise ValueError(
                f"A different task with id '{task.task_id}' already exists in workflow."
            )

        self._tasks[task.task_id] = task

        if auto_add_dependencies:
            for dep in task.dependencies:
                if dep.task_id not in self._tasks:
                    self.add_task(dep, auto_add_dependencies=True)

        return self

    def add_tasks(self, *tasks: Task, auto_add_dependencies: bool = True) -> Workflow:
        """Register multiple tasks into the workflow."""
        for t in tasks:
            self.add_task(t, auto_add_dependencies=auto_add_dependencies)
        return self

    def get_task(self, task_id_or_name: str) -> Task | None:
        """Look up a registered task by its task_id or task name."""
        if task_id_or_name in self._tasks:
            return self._tasks[task_id_or_name]
        for task in self._tasks.values():
            if task.name == task_id_or_name:
                return task
        return None

    def has_task(self, task_id_or_name: str) -> bool:
        """Return True if a task with the given task_id or name exists in the workflow."""
        return self.get_task(task_id_or_name) is not None

    def validate(self) -> None:
        """Validate workflow consistency, missing dependencies, and cycle absence.

        Raises:
            MissingDependencyError: If a task depends on a task outside this workflow.
            CircularDependencyError: If a circular dependency (cycle) is detected.
        """
        # 1. Verify all dependencies belong to this workflow
        for task in self._tasks.values():
            for dep in task.dependencies:
                if dep.task_id not in self._tasks:
                    raise MissingDependencyError(
                        f"Task '{task.name}' (id: {task.task_id}) depends on task "
                        f"'{dep.name}' (id: {dep.task_id}) which is not in this workflow."
                    )

        # 2. Cycle detection via topological sort validation (Kahn's Algorithm)
        self._detect_cycles()

    def _detect_cycles(self) -> None:
        """Check for cycles using in-degree reduction (Kahn's algorithm)."""
        in_degree: dict[str, int] = {t_id: 0 for t_id in self._tasks}
        adjacency: dict[str, list[str]] = defaultdict(list)

        for task_id, task in self._tasks.items():
            for dep in task.dependencies:
                adjacency[dep.task_id].append(task_id)
                in_degree[task_id] += 1

        queue = deque([t_id for t_id, deg in in_degree.items() if deg == 0])
        visited_count = 0

        while queue:
            curr_id = queue.popleft()
            visited_count += 1
            for neighbor_id in adjacency[curr_id]:
                in_degree[neighbor_id] -= 1
                if in_degree[neighbor_id] == 0:
                    queue.append(neighbor_id)

        if visited_count < len(self._tasks):
            cycle_path = self._find_cycle_path()
            path_str = " -> ".join(cycle_path) if cycle_path else "unknown cycle"
            raise CircularDependencyError(
                f"Circular dependency detected in workflow '{self.name}': {path_str}"
            )

    def _find_cycle_path(self) -> list[str]:
        """Find a representative cycle path using depth-first search."""
        visited: dict[str, int] = {}
        parent: dict[str, str] = {}
        cycle: list[str] = []

        def dfs(node_id: str) -> bool:
            visited[node_id] = 1
            task = self._tasks[node_id]
            downstream = [t for t in self._tasks.values() if task in t.dependencies]
            for nxt in downstream:
                if visited.get(nxt.task_id, 0) == 1:
                    curr = node_id
                    cycle.append(nxt.name)
                    cycle.append(self._tasks[curr].name)
                    while curr != nxt.task_id and curr in parent:
                        curr = parent[curr]
                        cycle.append(self._tasks[curr].name)
                    cycle.reverse()
                    return True
                elif visited.get(nxt.task_id, 0) == 0:
                    parent[nxt.task_id] = node_id
                    if dfs(nxt.task_id):
                        return True
            visited[node_id] = 2
            return False

        for t_id in self._tasks:
            if visited.get(t_id, 0) == 0:
                if dfs(t_id):
                    break
        return cycle

    def get_execution_order(self) -> list[Task]:
        """Compute a valid sequential topological execution order of tasks.

        Ensures that if Task B depends on Task A, Task A always appears before Task B.

        Returns:
            list[Task]: Topologically sorted list of tasks.

        Raises:
            CircularDependencyError: If a cycle exists.
            MissingDependencyError: If missing dependencies exist.
        """
        self.validate()

        in_degree: dict[str, int] = {t_id: 0 for t_id in self._tasks}
        adjacency: dict[str, list[str]] = defaultdict(list)

        for task_id, task in self._tasks.items():
            for dep in task.dependencies:
                adjacency[dep.task_id].append(task_id)
                in_degree[task_id] += 1

        queue = deque([t_id for t_id, deg in in_degree.items() if deg == 0])
        ordered_tasks: list[Task] = []

        while queue:
            curr_id = queue.popleft()
            ordered_tasks.append(self._tasks[curr_id])
            for neighbor_id in adjacency[curr_id]:
                in_degree[neighbor_id] -= 1
                if in_degree[neighbor_id] == 0:
                    queue.append(neighbor_id)

        return ordered_tasks

    def get_execution_batches(self) -> list[list[Task]]:
        """Compute topological tiers/generations for parallel or phased execution.

        Each batch contains tasks whose dependencies have all been satisfied in
        earlier batches, meaning tasks within the same batch can be executed concurrently.

        Returns:
            list[list[Task]]: Phased batches of tasks.
        """
        self.validate()

        in_degree: dict[str, int] = {t_id: 0 for t_id in self._tasks}
        adjacency: dict[str, list[str]] = defaultdict(list)

        for task_id, task in self._tasks.items():
            for dep in task.dependencies:
                adjacency[dep.task_id].append(task_id)
                in_degree[task_id] += 1

        current_batch = [t_id for t_id, deg in in_degree.items() if deg == 0]
        batches: list[list[Task]] = []

        while current_batch:
            batches.append([self._tasks[t_id] for t_id in current_batch])
            next_batch = []
            for curr_id in current_batch:
                for neighbor_id in adjacency[curr_id]:
                    in_degree[neighbor_id] -= 1
                    if in_degree[neighbor_id] == 0:
                        next_batch.append(neighbor_id)
            current_batch = next_batch

        return batches

    def get_downstream_tasks(self, task: Task) -> set[Task]:
        """Find immediate downstream tasks that declare this task as a dependency."""
        return {t for t in self._tasks.values() if task in t.dependencies}

    def get_all_downstream_tasks(self, task: Task) -> set[Task]:
        """Find all direct and indirect downstream tasks (transitive dependents).

        Useful for cascading BLOCKED status when a parent task fails.
        """
        downstream: set[Task] = set()
        queue = deque([task])

        while queue:
            curr = queue.popleft()
            immediate = self.get_downstream_tasks(curr)
            for child in immediate:
                if child not in downstream:
                    downstream.add(child)
                    queue.append(child)

        return downstream

    def reset(self) -> None:
        """Reset the workflow state and all constituent tasks for a re-run."""
        self.status = WorkflowStatus.PENDING
        for task in self._tasks.values():
            task.reset()

    def __len__(self) -> int:
        return len(self._tasks)

    def __iter__(self) -> Iterator[Task]:
        return iter(self._tasks.values())

    def __contains__(self, item: Task | str) -> bool:
        if isinstance(item, Task):
            return item.task_id in self._tasks
        return self.has_task(item)

    def __repr__(self) -> str:
        return (
            f"<Workflow id='{self.workflow_id}' name='{self.name}' "
            f"tasks={len(self._tasks)} status='{self.status.value}'>"
        )

"""Intermediate specification dataclasses for declarative workflows in Forge.

Provides value objects for workflows and tasks constructed from declarative data
structures (JSON/dict) before building executable Workflow DAG instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskSpec:
    """Specification for a single task within a declarative workflow.

    Attributes:
        id: Unique identifier for the task within the workflow.
        type: Task type registered in TaskRegistry (e.g., "http", "shell", "file", "function", or custom plugin type).
        name: Optional display name for the task (defaults to ``id`` if omitted).
        depends_on: List of task IDs that must succeed before this task runs.
        params: Task-specific construction arguments/parameters.
        max_retries: Number of retry attempts on execution failure.
        retry_delay: Delay in seconds between retries.
        failure_strategy: Policy on task failure ("STOP", "SKIP", "RETRY", "CONTINUE").
        timeout: Optional execution timeout in seconds.
        description: Optional human-readable task description.
    """

    id: str
    type: str
    name: str | None = None
    depends_on: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 0
    retry_delay: float = 0.0
    failure_strategy: str = "STOP"
    timeout: float | None = None
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSpec:
        """Construct a TaskSpec instance from a raw dictionary."""
        task_id = data.get("id")
        task_type = data.get("type")
        name = data.get("name")
        depends_on = data.get("depends_on", [])

        # Support params or parameters key
        params = data.get("params", data.get("parameters", {}))

        # Support retry_policy sub-dictionary or top-level keys
        retry_policy = data.get("retry_policy", {})
        if isinstance(retry_policy, dict):
            max_retries = data.get(
                "max_retries", retry_policy.get("max_retries", 0)
            )
            retry_delay = data.get(
                "retry_delay",
                retry_policy.get("delay", retry_policy.get("retry_delay", 0.0)),
            )
        else:
            max_retries = data.get("max_retries", 0)
            retry_delay = data.get("retry_delay", 0.0)

        failure_strategy = data.get("failure_strategy", "STOP")
        timeout = data.get("timeout")
        description = data.get("description", "")

        return cls(
            id=str(task_id) if task_id is not None else "",
            type=str(task_type) if task_type is not None else "",
            name=str(name) if name is not None else None,
            depends_on=[str(d) for d in depends_on] if isinstance(depends_on, list) else [],
            params=dict(params) if isinstance(params, dict) else {},
            max_retries=int(max_retries) if max_retries is not None else 0,
            retry_delay=float(retry_delay) if retry_delay is not None else 0.0,
            failure_strategy=str(failure_strategy).upper() if failure_strategy else "STOP",
            timeout=float(timeout) if timeout is not None else None,
            description=str(description) if description else "",
        )


@dataclass
class WorkflowSpec:
    """Specification for a declarative workflow DAG.

    Attributes:
        name: Required workflow name.
        workflow_id: Optional explicit workflow ID.
        description: Optional workflow description.
        parameters: Global runtime parameter defaults.
        metadata: Key-value metadata dictionary.
        tasks: Ordered list of TaskSpec items defining constituent tasks.
    """

    name: str
    workflow_id: str | None = None
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    tasks: list[TaskSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowSpec:
        """Construct a WorkflowSpec instance from a raw dictionary."""
        name = data.get("name")
        workflow_id = data.get("workflow_id") or data.get("id")
        description = data.get("description", "")
        parameters = data.get("parameters", {})
        metadata = data.get("metadata", {})
        raw_tasks = data.get("tasks", [])

        tasks_specs: list[TaskSpec] = []
        if isinstance(raw_tasks, list):
            for t_data in raw_tasks:
                if isinstance(t_data, dict):
                    tasks_specs.append(TaskSpec.from_dict(t_data))

        return cls(
            name=str(name) if name is not None else "",
            workflow_id=str(workflow_id) if workflow_id else None,
            description=str(description) if description else "",
            parameters=dict(parameters) if isinstance(parameters, dict) else {},
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
            tasks=tasks_specs,
        )

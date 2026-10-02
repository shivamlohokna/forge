"""Validation engine for declarative workflow specifications.

Performs strict pre-flight validation of workflow structures, task IDs, registry task types,
dependency references, configuration parameters, and code execution safety.
"""

from __future__ import annotations

from typing import Any

from forge.core.task import FailureStrategy
from forge.exceptions import WorkflowSpecError
from forge.registry.task_registry import TaskRegistry


def _check_safe_data(obj: Any, path: str) -> None:
    """Recursively verify that ``obj`` contains only pure data primitives.

    Raises:
        WorkflowSpecError: If executable code, callables, or non-declarative types are found.
    """
    if callable(obj) or hasattr(obj, "__code__"):
        raise WorkflowSpecError(
            f"Executable code or callable at '{path}' is not permitted in declarative workflows."
        )
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise WorkflowSpecError(
                    f"Dictionary key at '{path}' must be a string, got {type(k).__name__}."
                )
            _check_safe_data(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple, set)):
        for idx, item in enumerate(obj):
            _check_safe_data(item, f"{path}[{idx}]")
    elif obj is not None and not isinstance(obj, (str, int, float, bool)):
        raise WorkflowSpecError(
            f"Invalid non-declarative object type '{type(obj).__name__}' at '{path}'."
        )


def validate_workflow_dict(data: dict[str, Any], registry: TaskRegistry) -> None:
    """Validate a raw workflow dictionary against Forge constraints and ``registry``.

    Args:
        data: Raw dictionary defining the declarative workflow.
        registry: TaskRegistry instance to validate registered task types against.

    Raises:
        WorkflowSpecError: If any validation rule is violated.
        TypeError: If data is not a dict or registry is not a TaskRegistry.
    """
    if not isinstance(data, dict):
        raise WorkflowSpecError(f"Workflow definition must be a dict, got {type(data).__name__}.")

    if not isinstance(registry, TaskRegistry):
        raise TypeError(f"registry must be a TaskRegistry instance, got {type(registry).__name__}.")

    # 1. Code execution safety check
    _check_safe_data(data, "workflow")

    # 2. Validate workflow `name`
    name = data.get("name")
    if name is None or not isinstance(name, str) or not name.strip():
        raise WorkflowSpecError("Workflow 'name' is required and must be a non-empty string.")

    # 3. Validate `tasks` list
    tasks = data.get("tasks")
    if tasks is None or not isinstance(tasks, list):
        raise WorkflowSpecError("Workflow 'tasks' is required and must be a list.")

    if not tasks:
        raise WorkflowSpecError("Workflow 'tasks' list cannot be empty.")

    defined_ids: set[str] = set()
    valid_strategies = {s.value for s in FailureStrategy}

    # First pass: validate task structure and collect task IDs
    for idx, t_data in enumerate(tasks):
        path_prefix = f"tasks[{idx}]"
        if not isinstance(t_data, dict):
            raise WorkflowSpecError(f"{path_prefix} must be a dictionary.")

        # Validate task `id`
        t_id = t_data.get("id")
        if t_id is None or not isinstance(t_id, str) or not t_id.strip():
            raise WorkflowSpecError(f"{path_prefix}.id is required and must be a non-empty string.")

        clean_id = t_id.strip()
        if clean_id in defined_ids:
            raise WorkflowSpecError(
                f"Duplicate task id '{clean_id}' found at {path_prefix}."
            )
        defined_ids.add(clean_id)

        # Validate task `type` against TaskRegistry
        t_type = t_data.get("type")
        if t_type is None or not isinstance(t_type, str) or not t_type.strip():
            raise WorkflowSpecError(f"{path_prefix}.type is required and must be a non-empty string for task '{clean_id}'.")

        clean_type = t_type.strip()
        if clean_type not in registry:
            known = ", ".join(registry.list_types()) or "(none)"
            raise WorkflowSpecError(
                f"{path_prefix}.type: unknown task type '{clean_type}' for task '{clean_id}'. Registered types: {known}.\nNext step: Run 'forge tasks' to view registered task types."
            )

        # Validate failure strategy if present
        strat = t_data.get("failure_strategy")
        if strat is not None:
            if not isinstance(strat, str) or strat.upper() not in valid_strategies:
                raise WorkflowSpecError(
                    f"{path_prefix}.failure_strategy: invalid strategy '{strat}'. Must be one of: {sorted(valid_strategies)}."
                )

        # Validate max_retries if present
        retries = t_data.get("max_retries")
        if retries is not None:
            if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
                raise WorkflowSpecError(
                    f"{path_prefix}.max_retries: must be an integer >= 0, got {retries!r}."
                )

        # Validate timeout if present
        timeout = t_data.get("timeout")
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
                raise WorkflowSpecError(
                    f"{path_prefix}.timeout: must be a number > 0, got {timeout!r}."
                )

    # Second pass: validate dependency references
    for idx, t_data in enumerate(tasks):
        path_prefix = f"tasks[{idx}]"
        t_id = str(t_data.get("id")).strip()
        deps = t_data.get("depends_on", [])
        if not isinstance(deps, list):
            raise WorkflowSpecError(f"{path_prefix}.depends_on must be a list for task '{t_id}'.")

        for dep_idx, dep_id in enumerate(deps):
            if not isinstance(dep_id, str) or not dep_id.strip():
                raise WorkflowSpecError(
                    f"{path_prefix}.depends_on[{dep_idx}] must be a non-empty string."
                )
            clean_dep = dep_id.strip()
            if clean_dep not in defined_ids:
                raise WorkflowSpecError(
                    f"{path_prefix}.depends_on: task '{t_id}' depends on unknown task id '{clean_dep}'."
                )
            if clean_dep == t_id:
                raise WorkflowSpecError(
                    f"{path_prefix}.depends_on: task '{t_id}' cannot depend on itself."
                )

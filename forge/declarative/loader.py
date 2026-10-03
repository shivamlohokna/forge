"""Declarative workflow loader for Forge.

Parses declarative workflow definitions (dict, JSON, TOML, YAML), validates specifications,
instantiates tasks via TaskRegistry, wires DAG dependencies, and constructs
validated Workflow instances ready for Engine execution.

Phase 8.3 additions
───────────────────
- Environment variable interpolation (``${ENV_VAR}``) applied after parsing,
  before validation.  Missing variables raise ``WorkflowSpecError``.
- Schema-aware relative path resolution for ``file`` and ``shell`` task path
  parameters, resolved against the workflow file's parent directory.
  Arbitrary strings (``url``, ``repository``, ``title``, etc.) are never
  treated as filesystem paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.core.workflow import Workflow
from forge.declarative.interpolation import interpolate
from forge.declarative.parsers import (
    SUPPORTED_FORMAT_EXTENSIONS,
    parse_json,
    parse_workflow_file,
)
from forge.declarative.parameters import (
    parse_parameter_specs,
    resolve_and_validate_parameters,
    substitute_parameters,
)
from forge.declarative.spec import WorkflowSpec
from forge.declarative.validator import validate_workflow_dict
from forge.exceptions import WorkflowSpecError
from forge.registry.task_registry import TaskRegistry, get_default_registry

# ── Schema-aware path fields ──────────────────────────────────────────────────
#
# Only parameters that are **explicitly defined as path fields** by the task
# schema are resolved relative to the workflow file's parent directory.
# Arbitrary strings (url, repository, title, body, etc.) are never touched.
#
# Third-party plugin tasks may define their own path fields.  Phase 8 provides
# this resolution utility; plugins are responsible for declaring which of their
# parameters are paths (deferred to plugin API evolution).
#
_PATH_FIELDS_BY_TASK_TYPE: dict[str, frozenset[str]] = {
    "file":  frozenset({"path", "source", "destination"}),
    "shell": frozenset({"working_directory"}),
}


def _resolve_path_params(
    task_type: str,
    params: dict[str, Any],
    base_dir: Path,
) -> dict[str, Any]:
    """Resolve relative path parameters against *base_dir*.

    Only task parameters that are **explicitly listed as path fields** for
    the given *task_type* are touched.  All other string values are returned
    unchanged.

    Args:
        task_type: The normalized task type string (e.g. ``"file"``).
        params:    The raw parameter dict from the workflow spec.
        base_dir:  The parent directory of the workflow definition file.

    Returns:
        A new dict with eligible relative paths resolved.  Absolute paths and
        non-path parameters are returned as-is.
    """
    path_fields = _PATH_FIELDS_BY_TASK_TYPE.get(task_type.lower(), frozenset())
    if not path_fields:
        return params  # No path fields for this task type — fast exit

    resolved = dict(params)
    for field in path_fields:
        raw = resolved.get(field)
        if raw is None or not isinstance(raw, str):
            continue
        candidate = Path(raw)
        if candidate.is_absolute():
            continue  # Already absolute — leave unchanged
        resolved[field] = str(base_dir / candidate)
    return resolved


# ── Public API ────────────────────────────────────────────────────────────────

def load_declarative_workflow(
    data: dict[str, Any] | str | Path,
    registry: TaskRegistry | None = None,
    parameters: dict[str, Any] | None = None,
) -> Workflow:
    """Load a declarative workflow definition into a fully validated Workflow instance.

    Accepts:
    - Raw dictionary mapping
    - JSON content string
    - File path (Path or string) pointing to a .json, .toml, .yaml, or .yml file.

    Args:
        data: Workflow definition dictionary, JSON string, or file path.
        registry: Target TaskRegistry instance for resolving task types.
            Defaults to the process-wide default registry (includes built-in task types).
        parameters: Optional runtime parameter dictionary overriding/supplying parameter values.

    Returns:
        Fully constructed and validated Workflow DAG instance.

    Raises:
        WorkflowSpecError: If file parsing, env var interpolation, parameter validation,
            or workflow specification validation fails.
        TypeError: If data is not a dict, str, or Path.
    """
    target_registry = registry if registry is not None else get_default_registry()

    raw_dict: dict[str, Any]
    base_dir: Path | None = None  # Used for schema-aware path resolution

    if isinstance(data, Path):
        base_dir = data.parent.resolve()
        raw_dict = parse_workflow_file(data)
    elif isinstance(data, str):
        candidate = Path(data)
        # Check if data points to an existing file with a supported format extension
        if candidate.suffix.lower() in SUPPORTED_FORMAT_EXTENSIONS:
            base_dir = candidate.parent.resolve()
            raw_dict = parse_workflow_file(candidate)
        else:
            try:
                raw_dict = parse_json(data)
            except Exception as exc:
                if not candidate.exists() and candidate.suffix.lower() in SUPPORTED_FORMAT_EXTENSIONS:
                    raise WorkflowSpecError(f"Workflow file not found: '{data}'") from exc
                raise exc
    elif isinstance(data, dict):
        raw_dict = data
    else:
        raise TypeError(f"Workflow data must be a dict, str, or Path, got {type(data).__name__}.")

    # ── Phase 8.3.1: Environment variable interpolation ───────────────────────
    # Applied after parsing raw dict, before validation.  This means the
    # validator always sees resolved values (e.g., a real URL string rather
    # than "${API_URL}").
    try:
        raw_dict = interpolate(raw_dict)
    except WorkflowSpecError:
        raise  # propagate with original message
    except Exception as exc:
        raise WorkflowSpecError(
            f"Environment variable interpolation failed: {exc}"
        ) from exc

    # 1. Validate raw dictionary structure, parameters, and registry task types
    validate_workflow_dict(raw_dict, target_registry)

    # 2. Parse declared parameter specs, resolve/validate runtime inputs, and substitute
    raw_parameters = raw_dict.get("parameters", {})
    param_specs = parse_parameter_specs(raw_parameters)
    effective_parameters = resolve_and_validate_parameters(param_specs, parameters)

    substituted_dict = substitute_parameters(raw_dict, effective_parameters)

    # 3. Convert to WorkflowSpec structure
    spec = WorkflowSpec.from_dict(substituted_dict)


    # 3. Instantiate tasks via TaskRegistry (NO hardcoded if/elif task type branching!)
    id_to_task = {}
    for task_spec in spec.tasks:
        task_name = task_spec.name or task_spec.id

        params = task_spec.params

        # ── Phase 8.3.4: Schema-aware relative path resolution ────────────────
        # Only ``file`` and ``shell`` path fields are resolved; arbitrary
        # strings are never treated as filesystem paths.
        if base_dir is not None:
            params = _resolve_path_params(task_spec.type, params, base_dir)

        kwargs: dict[str, Any] = {
            "name": task_name,
            "task_id": task_spec.id,
            "max_retries": task_spec.max_retries,
            "retry_delay": task_spec.retry_delay,
            "failure_strategy": task_spec.failure_strategy,
            "description": task_spec.description,
            **params,
        }
        if task_spec.timeout is not None:
            kwargs["timeout"] = task_spec.timeout

        try:
            task = target_registry.create(task_spec.type, **kwargs)
        except Exception as exc:
            raise WorkflowSpecError(
                f"Failed to construct task '{task_spec.id}' of type '{task_spec.type}': {exc}"
            ) from exc

        id_to_task[task_spec.id] = task

    # 4. Wire DAG dependencies
    for task_spec in spec.tasks:
        child_task = id_to_task[task_spec.id]
        for dep_id in task_spec.depends_on:
            parent_task = id_to_task[dep_id]
            child_task.add_dependency(parent_task)

    # 5. Assemble Workflow DAG and run topological validation
    workflow = Workflow(
        name=spec.name,
        workflow_id=spec.workflow_id,
        description=spec.description,
        parameters=effective_parameters,
        metadata=spec.metadata,
    )
    workflow.add_tasks(*id_to_task.values())
    workflow.validate()

    return workflow

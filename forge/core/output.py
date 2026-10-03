"""Task output extraction, resolution, and template substitution engine for Forge.

This module provides the core data structures and functions for exposing,
validating, and referencing task outputs in Forge workflows.
"""

from __future__ import annotations

import re
from typing import Any

from forge.exceptions import OutputError, ParameterError

# Regex patterns for parameter and output template substitution:
# 1. Whole-value replacement: matches string that contains EXACTLY {{ expression }}
_EXACT_MATCH_PATTERN = re.compile(r"^\s*\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}\s*$")

# 2. String substitution: matches \{{ (escaped) or {{ expression }}
_SUBST_PATTERN = re.compile(
    r"\\\{\{"  # Escaped \{{ -> literal {{
    r"|"
    r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}"  # {{ expression }}
)


def get_structured_output(raw_output: Any) -> dict[str, Any]:
    """Convert any raw task output object into a JSON-compatible structured dictionary.

    Handles:
    - Dict outputs: returned directly.
    - Objects with a ``to_dict()`` method (e.g. ShellResult, HTTPResult): converted.
    - Primitive outputs (str, int, float, bool, list): wrapped into ``{"result": val, "value": val}``.
    - None: returns ``{}``.
    """
    if raw_output is None:
        return {}

    if isinstance(raw_output, dict):
        return raw_output

    if hasattr(raw_output, "to_dict") and callable(getattr(raw_output, "to_dict")):
        res = raw_output.to_dict()
        if isinstance(res, dict):
            return res

    if isinstance(raw_output, (str, int, float, bool, list)):
        return {"result": raw_output, "value": raw_output}

    return {"result": str(raw_output)}


def traverse_path(obj: Any, path: str) -> Any:
    """Traverse a dot-separated path into a nested dictionary, list, or object."""
    if not path:
        return obj

    parts = path.split(".")
    curr = obj

    for part in parts:
        if isinstance(curr, dict):
            if part in curr:
                curr = curr[part]
            else:
                available = ", ".join(sorted(str(k) for k in curr.keys())) if curr else "none"
                raise KeyError(f"Key '{part}' not found (available keys: {available})")
        elif isinstance(curr, list):
            try:
                idx = int(part)
                curr = curr[idx]
            except (ValueError, IndexError):
                raise KeyError(f"List index '{part}' out of range or invalid (list length: {len(curr)})")
        elif hasattr(curr, part):
            curr = getattr(curr, part)
        else:
            raise KeyError(f"Attribute '{part}' not found on object {curr!r}")

    return curr


def resolve_expression(
    expr: str,
    parameters: dict[str, Any] | None = None,
    outputs: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Resolve a template expression string (e.g., ``"outputs.fetch.body"`` or ``"source_file"``).

    Args:
        expr: Expression inside ``{{ ... }}``.
        parameters: Available parameter values dictionary.
        outputs: Available structured task outputs dictionary (mapped by task_id and task_name).

    Returns:
        The resolved value.

    Raises:
        OutputError: If output reference is invalid or missing.
        ParameterError: If parameter reference is invalid or missing.
    """
    params_ctx = parameters or {}
    outputs_ctx = outputs or {}

    expr = expr.strip()

    if expr.startswith("outputs."):
        # Output reference: outputs.<task_ref>.<path>
        output_ref = expr[8:]  # strip 'outputs.'
        if "." in output_ref:
            task_ref, field_path = output_ref.split(".", 1)
        else:
            task_ref, field_path = output_ref, ""

        if task_ref not in outputs_ctx:
            available_tasks = ", ".join(sorted(outputs_ctx.keys())) if outputs_ctx else "no completed tasks"
            raise OutputError(
                f"Missing output from task '{task_ref}' referenced in '{{{{ {expr} }}}}'.\n"
                f"Why: Task '{task_ref}' has not produced output or did not complete successfully.\n"
                f"Available task outputs: {available_tasks}.\n"
                f"Next Step: Ensure task '{task_ref}' is executed successfully before consuming its output."
            )

        task_output_dict = outputs_ctx[task_ref]

        if not field_path:
            return task_output_dict

        try:
            return traverse_path(task_output_dict, field_path)
        except KeyError as err:
            raise OutputError(
                f"Missing output field '{field_path}' in task '{task_ref}' referenced in '{{{{ {expr} }}}}'.\n"
                f"Why: {err}.\n"
                f"Next Step: Check the output keys produced by task '{task_ref}'."
            ) from err

    elif expr.startswith("parameters."):
        # Explicit parameter reference: parameters.<param_name>
        param_name = expr[11:]
        if param_name not in params_ctx:
            available_params = ", ".join(sorted(params_ctx.keys())) if params_ctx else "none"
            raise ParameterError(
                f"Parameter '{param_name}' referenced in '{{{{ {expr} }}}}' is not defined.\n"
                f"Why: Workflow references parameter '{param_name}' which was not supplied.\n"
                f"Next Step: Declare parameter '{param_name}' or pass --param {param_name}=<value> (available: {available_params})."
            )
        return params_ctx[param_name]

    else:
        # Implicit parameter reference: <param_name>
        param_name = expr
        if param_name in params_ctx:
            return params_ctx[param_name]
        
        # Fallback: check if it's an un-prefixed output reference
        if "." in param_name:
            task_ref, field_path = param_name.split(".", 1)
            if task_ref in outputs_ctx:
                try:
                    return traverse_path(outputs_ctx[task_ref], field_path)
                except KeyError:
                    pass

        available_params = ", ".join(sorted(params_ctx.keys())) if params_ctx else "none"
        raise ParameterError(
            f"Parameter '{param_name}' referenced in '{{{{ {expr} }}}}' is not defined.\n"
            f"Why: Workflow references parameter '{param_name}' which was not supplied.\n"
            f"Next Step: Declare parameter '{param_name}' or pass --param {param_name}=<value> (available: {available_params})."
        )


def substitute_template(
    data: Any,
    parameters: dict[str, Any] | None = None,
    outputs: dict[str, dict[str, Any]] | None = None,
    _depth: int = 0,
) -> Any:
    """Recursively substitute parameter and output placeholders in data structures.

    Type Preservation:
        If a string field is EXACTLY ``"{{ expression }}"``, the substituted value
        retains its original type (int, float, bool, dict, list).

    String Interpolation:
        If inside a larger string, the value is stringified.

    Escaping:
        ``\\{{ expression }}`` evaluates to literal ``{{ expression }}``.
    """
    if _depth > 50:
        return data

    if isinstance(data, dict):
        return {
            k: substitute_template(v, parameters, outputs, _depth=_depth + 1)
            for k, v in data.items()
        }

    if isinstance(data, list):
        return [
            substitute_template(item, parameters, outputs, _depth=_depth + 1)
            for item in data
        ]

    if isinstance(data, str):
        # 1. Whole-value exact match -> preserve primitive/object type
        exact_match = _EXACT_MATCH_PATTERN.fullmatch(data)
        if exact_match:
            expr = exact_match.group(1)
            return resolve_expression(expr, parameters, outputs)

        # 2. String substitution
        return _substitute_string(data, parameters, outputs)

    return data


def _substitute_string(
    text: str,
    parameters: dict[str, Any] | None = None,
    outputs: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Expand placeholders within a single text string."""
    result = []
    last_end = 0

    for match in _SUBST_PATTERN.finditer(text):
        result.append(text[last_end : match.start()])
        full_match = match.group(0)

        if full_match.startswith(r"\{{"):
            result.append("{{")
        else:
            expr = match.group(1)
            val = resolve_expression(expr, parameters, outputs)
            result.append(str(val))

        last_end = match.end()

    result.append(text[last_end:])
    return "".join(result)


def extract_expressions(data: Any) -> list[str]:
    """Scan data structure and return all referenced template expressions."""
    found: list[str] = []

    def _walk(item: Any) -> None:
        if isinstance(item, dict):
            for v in item.values():
                _walk(v)
        elif isinstance(item, list):
            for v in item:
                _walk(v)
        elif isinstance(item, str):
            exact = _EXACT_MATCH_PATTERN.fullmatch(item)
            if exact:
                found.append(exact.group(1).strip())
            else:
                for match in _SUBST_PATTERN.finditer(item):
                    if not match.group(0).startswith(r"\{{"):
                        found.append(match.group(1).strip())

    _walk(data)
    return found


def validate_output_references(workflow_dict: dict[str, Any]) -> None:
    """Statically validate output references in a raw declarative workflow dictionary.

    Enforces:
    1. Referenced task in ``outputs.task_id.field`` exists in the workflow.
    2. Referenced task is not self (no self-reference).
    3. Referenced task is an explicit upstream dependency in the DAG.

    Raises:
        OutputError: If any output reference rule is violated.
    """
    raw_tasks = workflow_dict.get("tasks", [])
    if not isinstance(raw_tasks, list):
        return

    task_map: dict[str, dict[str, Any]] = {}
    deps_map: dict[str, set[str]] = {}

    for task_dict in raw_tasks:
        if isinstance(task_dict, dict) and "id" in task_dict:
            tid = str(task_dict["id"])
            task_map[tid] = task_dict
            raw_deps = task_dict.get("depends_on", [])
            if isinstance(raw_deps, list):
                deps_map[tid] = {str(d) for d in raw_deps}
            else:
                deps_map[tid] = set()

    # Compute transitive upstream dependencies for each task
    def _get_transitive_upstream(tid: str, visited: set[str] | None = None) -> set[str]:
        if visited is None:
            visited = set()
        upstream = set()
        direct_deps = deps_map.get(tid, set())
        for d in direct_deps:
            if d not in visited:
                visited.add(d)
                upstream.add(d)
                upstream.update(_get_transitive_upstream(d, visited))
        return upstream

    for tid, task_dict in task_map.items():
        task_name = str(task_dict.get("name", tid))
        expressions = extract_expressions(task_dict.get("params", {}))

        # Check other task fields if present
        for extra_key in ("command", "url", "source", "destination", "content", "stdin"):
            if extra_key in task_dict:
                expressions.extend(extract_expressions(task_dict[extra_key]))

        transitive_deps = _get_transitive_upstream(tid)

        for expr in expressions:
            if expr.startswith("outputs."):
                ref_body = expr[8:]
                target_task = ref_body.split(".", 1)[0]

                # Rule 1: No self reference
                if target_task == tid or target_task == task_name:
                    raise OutputError(
                        f"Task '{tid}' cannot reference its own output '{{{{ {expr} }}}}'.\n"
                        f"Why: Task output references must point to prerequisite upstream tasks.\n"
                        f"Next Step: Remove self-referencing output placeholder from task '{tid}'."
                    )

                # Rule 2: Referenced task must exist
                if target_task not in task_map and not any(t.get("name") == target_task for t in task_map.values()):
                    declared = ", ".join(sorted(task_map.keys()))
                    raise OutputError(
                        f"Task '{tid}' references unknown task '{target_task}' in output expression '{{{{ {expr} }}}}'.\n"
                        f"Why: Task '{target_task}' is not declared in workflow.\n"
                        f"Next Step: Declare task '{target_task}' or fix spelling (declared tasks: {declared})."
                    )

                # Rule 3: Referenced task must be an upstream dependency
                target_id = target_task
                if target_task not in task_map:
                    # Resolve name to id
                    for k, v in task_map.items():
                        if v.get("name") == target_task:
                            target_id = k
                            break

                if target_id not in transitive_deps:
                    deps_list = ", ".join(sorted(deps_map.get(tid, set()))) or "none"
                    raise OutputError(
                        f"Task '{tid}' references output of task '{target_task}' ('{{{{ {expr} }}}}') but '{target_task}' is not in 'depends_on'.\n"
                        f"Why: Tasks can only consume outputs from declared prerequisite dependencies.\n"
                        f"Next Step: Add '{target_task}' to 'depends_on' for task '{tid}' (current depends_on: {deps_list})."
                    )


__all__ = [
    "get_structured_output",
    "traverse_path",
    "resolve_expression",
    "substitute_template",
    "extract_expressions",
    "validate_output_references",
]


"""Workflow loader for Forge CLI.

Loads Python workflow definitions (.py) and declarative workflow definitions
(.json, .toml, .yaml, .yml) from file paths.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

from forge.core.workflow import Workflow
from forge.declarative import load_declarative_workflow
from forge.declarative.parsers import SUPPORTED_FORMAT_EXTENSIONS
from forge.exceptions import LoadError, WorkflowSpecError
from forge.registry.task_registry import TaskRegistry


import inspect
from typing import Any

from forge.declarative.parsers import parse_workflow_file


def parse_cli_parameter_args(
    param_list: list[str] | None = None,
    params_file: str | Path | None = None,
) -> dict[str, Any]:
    """Parse CLI --param and --params inputs into a unified parameters dictionary.

    Args:
        param_list: List of key=value parameter strings from CLI ``--param``.
        params_file: Path to a JSON, TOML, or YAML parameter file from CLI ``--params``.

    Returns:
        dict[str, Any]: Combined parameters dictionary.

    Raises:
        LoadError: If parameter file is missing/invalid or --param format is invalid.
    """
    combined: dict[str, Any] = {}

    if params_file:
        file_path = Path(params_file).resolve()
        if not file_path.exists():
            raise LoadError(f"Parameter file not found: '{params_file}'")
        try:
            file_params = parse_workflow_file(file_path)
            if not isinstance(file_params, dict):
                raise LoadError(
                    f"Parameter file '{params_file}' must contain a key-value dictionary."
                )
            combined.update(file_params)
        except Exception as exc:
            if isinstance(exc, LoadError):
                raise
            raise LoadError(f"Failed to parse parameter file '{params_file}': {exc}") from exc

    if param_list:
        for item in param_list:
            if "=" not in item:
                raise LoadError(
                    f"Invalid parameter format '{item}'. Expected key=value (e.g. --param key=value)."
                )
            key, val_str = item.split("=", 1)
            key = key.strip()
            if not key:
                raise LoadError(
                    f"Invalid parameter format '{item}'. Parameter key cannot be empty."
                )

            val_lower = val_str.strip().lower()
            if val_lower == "true":
                parsed_val: Any = True
            elif val_lower == "false":
                parsed_val = False
            else:
                try:
                    parsed_val = int(val_str)
                except ValueError:
                    try:
                        parsed_val = float(val_str)
                    except ValueError:
                        parsed_val = val_str

            combined[key] = parsed_val

    return combined



def load_workflow(
    path: str | Path,
    parameters: dict[str, Any] | None = None,
) -> Workflow:
    """Load a Workflow instance from a Python or declarative file (.json, .toml, .yaml, .yml).

    Args:
        path: Path to the workflow file.
        parameters: Optional dictionary of runtime parameters.

    Returns:
        A Workflow instance.

    Raises:
        LoadError: If the file does not exist, cannot be parsed, or fails validation.
    """
    file_path = Path(path).resolve()

    if not file_path.exists():
        raise LoadError(f"Workflow file not found: {file_path}")

    ext = file_path.suffix.lower()

    # Declarative formats (.json, .toml, .yaml, .yml)
    if ext in SUPPORTED_FORMAT_EXTENSIONS:
        registry = TaskRegistry()
        from forge.registry.builtins import register_builtin_tasks
        register_builtin_tasks(registry)
        try:
            from forge.plugins import load_plugins
            load_plugins(registry)
        except Exception:
            pass
        try:
            return load_declarative_workflow(file_path, registry=registry, parameters=parameters)
        except WorkflowSpecError as err:
            raise LoadError(str(err)) from err
        except Exception as err:
            raise LoadError(f"Failed to load declarative workflow '{file_path}': {err}") from err

    # Python workflow definition (.py)
    if ext != ".py":
        supported = ", ".join(sorted([".py"] + list(SUPPORTED_FORMAT_EXTENSIONS)))
        raise LoadError(
            f"Unsupported workflow file format '{ext}'. Supported formats: {supported}"
        )

    module_name = f"_forge_wf_{file_path.stem}_{uuid.uuid4().hex[:8]}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec is None or spec.loader is None:
            raise LoadError(f"Unable to load specification for workflow file: {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except LoadError:
        raise
    except Exception as e:
        raise LoadError(f"Error executing workflow file '{file_path}': {e}") from e
    finally:
        # Clean up temporary module from sys.modules to avoid namespace pollution
        sys.modules.pop(module_name, None)

    wf: Workflow | None = None

    # Contract 1: get_workflow() callable
    if hasattr(module, "get_workflow"):
        candidate = getattr(module, "get_workflow")
        if not callable(candidate):
            raise LoadError(f"'get_workflow' in '{file_path}' is not callable.")
        try:
            sig = inspect.signature(candidate)
            if "parameters" in sig.parameters or len(sig.parameters) > 0:
                wf = candidate(parameters=parameters or {})
            else:
                wf = candidate()
        except Exception as e:
            raise LoadError(f"Error calling 'get_workflow()' in '{file_path}': {e}") from e

        if not isinstance(wf, Workflow):
            raise LoadError(
                f"'get_workflow()' in '{file_path}' must return a Workflow instance, "
                f"got {type(wf).__name__}."
            )

    # Contract 2: module-level workflow variable
    elif hasattr(module, "workflow"):
        wf = getattr(module, "workflow")
        if not isinstance(wf, Workflow):
            raise LoadError(
                f"'workflow' attribute in '{file_path}' must be a Workflow instance, "
                f"got {type(wf).__name__}."
            )
    else:
        raise LoadError(
            f"Workflow file '{file_path}' must define either a 'get_workflow()' function "
            f"or a module-level 'workflow' variable."
        )

    if parameters and wf is not None:
        wf.parameters = {**wf.parameters, **parameters}

    return wf


"""Workflow parameter specification, validation, and substitution for Forge.

Provides parameter declaration parsing, pre-flight validation, type coercion,
and safe deterministic template substitution (``{{ param_name }}``) for
declarative workflows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from forge.exceptions import ParameterError


VALID_PARAM_TYPES = frozenset({"string", "integer", "number", "boolean"})

_TYPE_ALIASES = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
}

# Regex patterns for parameter substitution:
# 1. Whole-value replacement: matches string that contains EXACTLY {{ param_name }}
_EXACT_MATCH_PATTERN = re.compile(r"^\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\s*$")

# 2. String substitution: matches \{{ (escaped) or {{ param_name }}
_SUBST_PATTERN = re.compile(
    r"\\\{\{"  # Escaped \{{ -> literal {{
    r"|"
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}"  # {{ param_name }}
)


@dataclass
class ParameterSpec:
    """Specification for a workflow parameter.

    Attributes:
        name: Parameter identifier name.
        type: Declared type ("string", "integer", "number", "boolean").
        required: Whether the parameter must be provided at runtime.
        default: Default value if parameter is omitted.
        description: Human-readable description.
        secret: Whether parameter contains sensitive data and should be masked.
    """

    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""
    secret: bool = False

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any] | Any) -> ParameterSpec:
        """Construct a ParameterSpec from shorthand or full dictionary spec."""
        if not isinstance(data, dict):
            # Shorthand notation: "param_name": default_value
            default_val = data
            type_name = _infer_type(default_val)
            return cls(
                name=name,
                type=type_name,
                required=False,
                default=default_val,
                description="",
                secret=False,
            )

        raw_type = str(data.get("type", "string")).lower().strip()
        type_name = _TYPE_ALIASES.get(raw_type)
        if type_name is None:
            raise ParameterError(
                f"Invalid parameter type '{raw_type}' for parameter '{name}'.\n"
                f"Why: Supported types are: string, integer, number, boolean.\n"
                f"Next Step: Change 'type' for parameter '{name}' to a supported type."
            )

        has_default = "default" in data
        default_val = data.get("default", None)
        required = bool(data.get("required", not has_default))
        description = str(data.get("description", ""))
        secret = bool(data.get("secret", False))

        return cls(
            name=name,
            type=type_name,
            required=required,
            default=default_val,
            description=description,
            secret=secret,
        )


def _infer_type(val: Any) -> str:
    """Infer parameter type name from Python runtime value."""
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    return "string"


def parse_parameter_specs(raw_parameters: dict[str, Any]) -> dict[str, ParameterSpec]:
    """Parse a workflow's declared parameters dictionary into ParameterSpec instances."""
    specs: dict[str, ParameterSpec] = {}
    if not isinstance(raw_parameters, dict):
        raise ParameterError(
            f"Workflow 'parameters' must be a dictionary mapping parameter names to specifications, "
            f"got {type(raw_parameters).__name__}."
        )

    for name, decl in raw_parameters.items():
        specs[name] = ParameterSpec.from_dict(name, decl)

    return specs


def resolve_and_validate_parameters(
    specs: dict[str, ParameterSpec],
    user_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve and validate user parameters against declared parameter specifications.

    Args:
        specs: Parsed dictionary of parameter specs from workflow declaration.
        user_params: Dictionary of runtime parameters supplied by user/CLI.

    Returns:
        dict[str, Any]: Resolved dictionary of typed effective parameters.

    Raises:
        ParameterError: If unknown parameter is passed, required parameter is missing,
            or type validation fails.
    """
    user_provided = dict(user_params or {})

    # 1. Reject unknown parameters
    for key in user_provided:
        if key not in specs:
            valid_names = ", ".join(sorted(specs.keys())) if specs else "none declared"
            raise ParameterError(
                f"Unknown parameter '{key}'.\n"
                f"Why: Parameter '{key}' was supplied but is not declared in the workflow parameter specification.\n"
                f"Next Step: Remove unknown parameter or declare '{key}' in workflow parameters ({valid_names})."
            )

    resolved: dict[str, Any] = {}

    # 2. Validate declared parameters
    for name, spec in specs.items():
        if name in user_provided and user_provided[name] is not None:
            raw_val = user_provided[name]
        elif spec.default is not None:
            raw_val = spec.default
        elif not spec.required:
            raw_val = spec.default
        else:
            raise ParameterError(
                f"Parameter '{name}' is required.\n"
                f"Why: Workflow parameter '{name}' is marked as required and no value or default was provided.\n"
                f"Next Step: Pass '--param {name}=<value>' when running or planning the workflow."
            )

        if raw_val is None:
            if spec.required:
                raise ParameterError(
                    f"Parameter '{name}' is required.\n"
                    f"Why: Workflow parameter '{name}' is marked as required.\n"
                    f"Next Step: Pass '--param {name}=<value>'."
                )
            resolved[name] = None
            continue

        resolved[name] = _coerce_and_validate_type(name, raw_val, spec.type)

    return resolved


def _coerce_and_validate_type(name: str, val: Any, expected_type: str) -> Any:
    """Coerce and validate parameter value against expected type."""
    if expected_type == "string":
        if isinstance(val, (dict, list)):
            raise ParameterError(
                f"Type mismatch for parameter '{name}': expected string, received {type(val).__name__}.\n"
                f"Why: Parameter '{name}' declared as string cannot accept complex object.\n"
                f"Next Step: Pass a valid string value for parameter '{name}'."
            )
        return str(val)

    if expected_type == "integer":
        if isinstance(val, bool):
            raise ParameterError(
                f"Type mismatch for parameter '{name}': expected integer, received boolean '{val}'.\n"
                f"Why: Parameter '{name}' is declared as integer.\n"
                f"Next Step: Pass a valid integer (e.g., --param {name}=10)."
            )
        try:
            return int(val)
        except (ValueError, TypeError):
            raise ParameterError(
                f"Parameter '{name}' expects integer, received '{val}'.\n"
                f"Why: Cannot parse '{val}' as an integer.\n"
                f"Next Step: Pass a valid integer (e.g., --param {name}=10)."
            )

    if expected_type == "number":
        if isinstance(val, bool):
            raise ParameterError(
                f"Type mismatch for parameter '{name}': expected number, received boolean '{val}'.\n"
                f"Why: Parameter '{name}' is declared as number.\n"
                f"Next Step: Pass a valid numeric value."
            )
        try:
            res = float(val)
            # Retain int type if input was int
            if isinstance(val, int):
                return val
            return res
        except (ValueError, TypeError):
            raise ParameterError(
                f"Parameter '{name}' expects number, received '{val}'.\n"
                f"Why: Cannot parse '{val}' as a numeric float/int.\n"
                f"Next Step: Pass a valid numeric value."
            )

    if expected_type == "boolean":
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            if val in (0, 1):
                return bool(val)
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("true", "1", "yes", "on"):
                return True
            if s in ("false", "0", "no", "off"):
                return False

        raise ParameterError(
            f"Parameter '{name}' expects boolean, received '{val}'.\n"
            f"Why: Parameter '{name}' declared as boolean requires true/false.\n"
            f"Next Step: Pass true or false for parameter '{name}'."
        )

    return val


def substitute_parameters(
    data: Any,
    params: dict[str, Any],
    _depth: int = 0,
) -> Any:
    """Recursively substitute ``{{ param_name }}`` placeholders in data structures.

    Type Preservation:
        If a field value string is EXACTLY ``"{{ param_name }}"``, the substituted
        value retains its original primitive type (int, bool, float, etc.).
        If inside a larger string, the value is stringified.

    Escaping:
        ``\\{{ param_name }}`` outputs literal ``{{ param_name }}``.
    """
    if _depth > 50:
        return data

    if isinstance(data, dict):
        return {
            # Keys are never substituted — only dictionary values.
            k: substitute_parameters(v, params, _depth=_depth + 1)
            for k, v in data.items()
        }

    if isinstance(data, list):
        return [substitute_parameters(item, params, _depth=_depth + 1) for item in data]

    if isinstance(data, str):
        # 1. Whole-value exact match -> preserve primitive type
        exact_match = _EXACT_MATCH_PATTERN.fullmatch(data)
        if exact_match:
            param_name = exact_match.group(1)
            if param_name not in params:
                raise ParameterError(
                    f"Parameter '{param_name}' referenced in template '{{{{ {param_name} }}}}' is not defined.\n"
                    f"Why: Workflow references parameter '{param_name}' which was not provided or declared.\n"
                    f"Next Step: Declare parameter '{param_name}' or pass --param {param_name}=<value>."
                )
            return params[param_name]

        # 2. String substitution
        return _substitute_string(data, params)

    return data


def _substitute_string(text: str, params: dict[str, Any]) -> str:
    """Expand placeholders in a single string."""
    result = []
    last_end = 0

    for match in _SUBST_PATTERN.finditer(text):
        result.append(text[last_end : match.start()])
        full_match = match.group(0)

        if full_match.startswith(r"\{{"):
            # Escaped \{{ -> produce {{
            result.append("{{")
        else:
            param_name = match.group(1)
            if param_name not in params:
                raise ParameterError(
                    f"Parameter '{param_name}' referenced in template '{full_match}' is not defined.\n"
                    f"Why: Workflow references parameter '{param_name}' which was not provided or declared.\n"
                    f"Next Step: Declare parameter '{param_name}' or pass --param {param_name}=<value>."
                )
            result.append(str(params[param_name]))

        last_end = match.end()

    result.append(text[last_end:])
    return "".join(result)


def mask_secret_parameters(
    params: dict[str, Any],
    specs: dict[str, ParameterSpec] | None = None,
) -> dict[str, Any]:
    """Return a shallow copy of parameters with sensitive/secret values masked."""
    masked = {}
    specs = specs or {}
    for k, v in params.items():
        spec = specs.get(k)
        if spec and spec.secret:
            masked[k] = "********"
        else:
            masked[k] = v
    return masked


__all__ = [
    "ParameterSpec",
    "parse_parameter_specs",
    "resolve_and_validate_parameters",
    "substitute_parameters",
    "mask_secret_parameters",
]

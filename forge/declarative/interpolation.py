"""Environment variable interpolation for Forge declarative workflows.

This module provides ``interpolate()``, which recursively expands
``${ENV_VAR}`` references in declarative workflow strings.

Design
──────
The following semantics are **explicitly locked in** and must not be changed
without a corresponding change to the Phase 8.3 specification:

1. ``${VAR}`` where ``VAR`` is set in the environment
      → replaced with the environment variable's string value.

2. ``${VAR}`` where ``VAR`` is **not** set in the environment
      → raises ``WorkflowSpecError`` with a clear message:
        *"Environment variable 'VAR' is not defined"*
      Rationale: a typo must not silently become an empty credential or path.

3. ``$${VAR}`` (double-dollar escape)
      → literal ``${VAR}`` — no substitution is performed.

4. Only environment variable **names** are matched — the pattern allows
   only word characters and underscores (``[A-Za-z_][A-Za-z0-9_]*``).
   Arbitrary expressions, shell constructs, and code snippets inside
   ``${}`` are **not** evaluated.  Forge explicitly rejects Jinja/code
   execution in declarative files.

5. Interpolation is applied **recursively** over ``dict`` / ``list`` /
   ``str`` values.  Dictionary **keys** are never interpolated.

Usage
─────
The declarative loader calls ``interpolate()`` after parsing the raw dict
and before ``validate_workflow_dict()``, so the validator always sees
resolved values.

::

    from forge.declarative.interpolation import interpolate

    os.environ["GITHUB_TOKEN"] = "ghp_abc"
    result = interpolate({"token": "${GITHUB_TOKEN}"})
    # → {"token": "ghp_abc"}

    interpolate({"url": "${NOT_DEFINED}"})
    # → raises WorkflowSpecError: "Environment variable 'NOT_DEFINED' is not defined"

    interpolate({"literal": "$${ESCAPED}"})
    # → {"literal": "${ESCAPED}"}
"""

from __future__ import annotations

import os
import re
from typing import Any

from forge.exceptions import WorkflowSpecError

# ── Pattern ───────────────────────────────────────────────────────────────────
#
# Matches two alternative forms:
#   Group 1 (``double``):  ``$${...}``  → literal passthrough
#   Group 2 (``name``):    ``${VAR}``   → environment variable lookup
#
# Only valid identifier characters are accepted in group 2
# (``[A-Za-z_][A-Za-z0-9_]*``).  Anything else (expressions, spaces,
# arithmetic) is not matched and is left in the string unchanged.
_PATTERN: re.Pattern[str] = re.compile(
    r"\$\$\{([A-Za-z_][A-Za-z0-9_]*)\}"   # $${ VAR } → literal ${VAR}
    r"|"
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}"     # ${ VAR }  → os.environ lookup
)


# ── Public API ────────────────────────────────────────────────────────────────

def interpolate(value: Any, *, _depth: int = 0) -> Any:
    """Recursively expand ``${ENV_VAR}`` references in *value*.

    Args:
        value: Any declarative workflow value.  May be a ``dict``, ``list``,
               ``str``, or any other type.

    Returns:
        A new object with all ``${VAR}`` references expanded.  The original
        object is never mutated.

    Raises:
        WorkflowSpecError: If a referenced environment variable is not set.
    """
    if _depth > 50:
        # Guard against pathological circular structures (shouldn't occur in
        # parsed YAML/JSON/TOML, but be safe).
        return value

    if isinstance(value, dict):
        return {
            # Keys are never interpolated — only values.
            k: interpolate(v, _depth=_depth + 1)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [interpolate(item, _depth=_depth + 1) for item in value]

    if isinstance(value, str):
        return _expand_string(value)

    # Non-string scalars (int, float, bool, None) are returned as-is.
    return value


def _expand_string(text: str) -> str:
    """Expand all ``${VAR}`` references in a single string.

    Args:
        text: A raw string potentially containing ``${...}`` references.

    Returns:
        The string with all references expanded.

    Raises:
        WorkflowSpecError: If any referenced variable is not found in
            ``os.environ``.
    """
    result = []
    last_end = 0

    for match in _PATTERN.finditer(text):
        # Append everything before this match verbatim
        result.append(text[last_end : match.start()])

        escaped_name = match.group(1)  # From $${VAR} → literal ${VAR}
        env_name = match.group(2)      # From ${VAR}  → lookup

        if escaped_name is not None:
            # $${VAR} → produce a literal ${VAR}
            result.append(f"${{{escaped_name}}}")
        else:
            # ${VAR} → resolve from environment
            env_value = os.environ.get(env_name)
            if env_value is None:
                raise WorkflowSpecError(
                    f"Environment variable '{env_name}' is not defined. "
                    f"Set it before running 'forge run', or remove the "
                    f"'${{{env_name}}}' reference from your workflow file."
                )
            result.append(env_value)

        last_end = match.end()

    # Append any remaining text after the last match
    result.append(text[last_end:])
    return "".join(result)


# ── Module exports ────────────────────────────────────────────────────────────

__all__ = ["interpolate"]

"""TOML format parser for declarative workflows in Forge."""

from __future__ import annotations

import tomllib
from typing import Any

from forge.exceptions import WorkflowSpecError


def parse_toml(content: str | bytes) -> dict[str, Any]:
    """Parse TOML string or bytes into a normalized dictionary.

    Args:
        content: TOML string or byte sequence.

    Returns:
        Parsed dictionary.

    Raises:
        WorkflowSpecError: If TOML parsing fails or top-level structure is not a dict.
    """
    try:
        if isinstance(content, str):
            data = tomllib.loads(content)
        elif isinstance(content, bytes):
            data = tomllib.loads(content.decode("utf-8"))
        else:
            raise TypeError(f"Expected str or bytes, got {type(content).__name__}")
    except tomllib.TOMLDecodeError as exc:
        raise WorkflowSpecError(f"Failed to parse TOML workflow definition: {exc}") from exc
    except Exception as exc:
        raise WorkflowSpecError(f"Error reading TOML workflow content: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowSpecError(
            f"TOML workflow definition must be a table (dict), got {type(data).__name__}."
        )

    return data

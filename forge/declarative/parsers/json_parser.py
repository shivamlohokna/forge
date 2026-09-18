"""JSON format parser for declarative workflows in Forge."""

from __future__ import annotations

import json
from typing import Any

from forge.exceptions import WorkflowSpecError


def parse_json(content: str | bytes) -> dict[str, Any]:
    """Parse JSON string or bytes into a normalized dictionary.

    Args:
        content: JSON string or byte sequence.

    Returns:
        Parsed dictionary.

    Raises:
        WorkflowSpecError: If JSON parsing fails or top-level structure is not a dict.
    """
    try:
        data = json.loads(content)
    except Exception as exc:
        raise WorkflowSpecError(f"Failed to parse JSON workflow definition: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowSpecError(
            f"JSON workflow definition must be a object (dict), got {type(data).__name__}."
        )

    return data

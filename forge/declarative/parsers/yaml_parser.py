"""YAML format parser for declarative workflows in Forge.

Provides optional YAML format support using PyYAML if installed.
"""

from __future__ import annotations

from typing import Any

from forge.exceptions import WorkflowSpecError

YAML_AVAILABLE = False
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None  # type: ignore[assignment]


def parse_yaml(content: str | bytes) -> dict[str, Any]:
    """Parse YAML string or bytes into a normalized dictionary.

    Args:
        content: YAML string or byte sequence.

    Returns:
        Parsed dictionary.

    Raises:
        WorkflowSpecError: If PyYAML is not installed, or if YAML parsing fails.
    """
    if not YAML_AVAILABLE or yaml is None:
        raise WorkflowSpecError(
            "YAML workflow support requires the 'pyyaml' package. Install it using 'pip install pyyaml'."
        )

    try:
        data = yaml.safe_load(content)
    except Exception as exc:
        raise WorkflowSpecError(f"Failed to parse YAML workflow definition: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowSpecError(
            f"YAML workflow definition must be a mapping (dict), got {type(data).__name__}."
        )

    return data

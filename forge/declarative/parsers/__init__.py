"""Format parsers for declarative workflow files (JSON, TOML, YAML)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.declarative.parsers.json_parser import parse_json
from forge.declarative.parsers.toml_parser import parse_toml
from forge.declarative.parsers.yaml_parser import parse_yaml
from forge.exceptions import WorkflowSpecError

SUPPORTED_FORMAT_EXTENSIONS: set[str] = {".json", ".toml", ".yaml", ".yml"}


def parse_workflow_file(path: str | Path) -> dict[str, Any]:
    """Parse a workflow file into a normalized dictionary based on its file extension.

    Args:
        path: Path to a workflow definition file (.json, .toml, .yaml, .yml).

    Returns:
        Parsed dictionary representation of the workflow.

    Raises:
        WorkflowSpecError: If file does not exist, extension is unsupported, or parsing fails.
    """
    file_path = Path(path).resolve()
    if not file_path.exists():
        raise WorkflowSpecError(f"Workflow file not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_FORMAT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_FORMAT_EXTENSIONS))
        raise WorkflowSpecError(
            f"Unsupported workflow file extension '{ext}'. Supported extensions: {supported}."
        )

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise WorkflowSpecError(f"Cannot read workflow file '{file_path}': {exc}") from exc

    if ext == ".json":
        return parse_json(content)
    elif ext == ".toml":
        return parse_toml(content)
    elif ext in (".yaml", ".yml"):
        return parse_yaml(content)

    raise WorkflowSpecError(f"Unhandled file extension '{ext}' for file '{file_path}'.")

"""Forge Command-Line Interface (CLI)."""

from forge.cli.loader import load_workflow
from forge.cli.commands import (
    doctor_command,
    examples_command,
    history_command,
    init_command,
    inspect_command,
    run_command,
    status_command,
    tasks_command,
    validate_command,
)

__all__ = [
    "doctor_command",
    "examples_command",
    "history_command",
    "init_command",
    "inspect_command",
    "load_workflow",
    "run_command",
    "status_command",
    "tasks_command",
    "validate_command",
]


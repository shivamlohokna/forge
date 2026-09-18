"""Built-in task type registrations.

Kept separate from the Engine: importing this module only populates a
:class:`TaskRegistry`.  Workflow authors can still instantiate task classes
directly; the registry exists so loaders can resolve ``"type": "http"``.
"""

from __future__ import annotations

from forge.registry.task_registry import TaskRegistry
from forge.tasks.file_task import FileTask
from forge.tasks.function_task import FunctionTask
from forge.tasks.http_task import HTTPTask
from forge.tasks.shell_task import ShellTask

BUILTIN_TASK_TYPES: dict[str, type] = {
    "function": FunctionTask,
    "file": FileTask,
    "shell": ShellTask,
    "http": HTTPTask,
}


def register_builtin_tasks(registry: TaskRegistry) -> None:
    """Register Forge's four concrete task types on ``registry``.

    Existing names are left unchanged so this is safe to call more than once
    on the same registry.
    """
    for task_type, factory in BUILTIN_TASK_TYPES.items():
        if task_type not in registry:
            registry.register(task_type, factory)

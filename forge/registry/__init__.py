"""Task registry: construction-time lookup of task types.

This package is the seam between workflow loading and the Engine.  The
Engine executes ``Task`` instances and never imports this module.
"""

from forge.exceptions import DuplicateTaskTypeError, UnknownTaskTypeError
from forge.registry.builtins import BUILTIN_TASK_TYPES, register_builtin_tasks
from forge.registry.task_registry import (
    TaskFactory,
    TaskRegistry,
    create,
    get_default_registry,
    list_types,
    register,
    resolve,
    unregister,
)

register_builtin_tasks(get_default_registry())

__all__ = [
    "BUILTIN_TASK_TYPES",
    "DuplicateTaskTypeError",
    "TaskFactory",
    "TaskRegistry",
    "UnknownTaskTypeError",
    "create",
    "get_default_registry",
    "list_types",
    "register",
    "register_builtin_tasks",
    "resolve",
    "unregister",
]

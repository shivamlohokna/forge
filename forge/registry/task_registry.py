"""Task type registry for Forge.

The registry maps a string task type (e.g. ``"http"``) to a factory or Task
subclass.  It belongs at the workflow construction / loading boundary.

The Engine must not import or consult this module: it only executes ``Task``
instances that have already been constructed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TypeAlias

from forge.core.task import Task
from forge.exceptions import DuplicateTaskTypeError, UnknownTaskTypeError

TaskFactory: TypeAlias = Callable[..., Task]


def _normalize_type(task_type: str) -> str:
    """Return the canonical registry key for a task type name."""
    if not isinstance(task_type, str):
        raise TypeError(
            f"Task type must be a string, got {type(task_type).__name__}"
        )
    key = task_type.strip().lower()
    if not key:
        raise ValueError("Task type cannot be empty.")
    return key


class TaskRegistry:
    """In-memory mapping of task type names to constructors.

    Typical use::

        registry.register("http", HTTPTask)
        factory = registry.resolve("http")
        task = registry.create("http", name="ping", url="https://example.com")
    """

    def __init__(self) -> None:
        self._types: dict[str, TaskFactory] = {}

    def register(
        self,
        task_type: str,
        factory: TaskFactory,
    ) -> None:
        """Register ``factory`` under ``task_type``.

        Args:
            task_type: Canonical name used in declarative workflows
                (e.g. ``"http"``).  Compared case-insensitively.
            factory: A ``Task`` subclass or callable that returns a ``Task``.

        Raises:
            DuplicateTaskTypeError: If ``task_type`` is already registered.
            TypeError: If ``factory`` is not callable.
            ValueError: If ``task_type`` is empty.
        """
        key = _normalize_type(task_type)
        if not callable(factory):
            raise TypeError(
                f"Task factory for '{key}' must be callable, "
                f"got {type(factory).__name__}"
            )
        if key in self._types:
            raise DuplicateTaskTypeError(
                f"Task type '{key}' is already registered"
            )
        self._types[key] = factory

    def resolve(self, task_type: str) -> TaskFactory:
        """Return the factory registered for ``task_type``.

        Raises:
            UnknownTaskTypeError: If the type has not been registered.
        """
        key = _normalize_type(task_type)
        try:
            return self._types[key]
        except KeyError:
            known = ", ".join(self.list_types()) or "(none)"
            raise UnknownTaskTypeError(
                f"Unknown task type '{key}'. Registered types: {known}"
            ) from None

    def create(self, task_type: str, *args, **kwargs) -> Task:
        """Construct a task by resolving ``task_type`` and calling its factory.

        Raises:
            UnknownTaskTypeError: If the type has not been registered.
            TypeError: If the factory does not return a ``Task`` instance.
        """
        factory = self.resolve(task_type)
        task = factory(*args, **kwargs)
        if not isinstance(task, Task):
            raise TypeError(
                f"Factory for task type '{_normalize_type(task_type)}' "
                f"must return a Task instance, got {type(task).__name__}"
            )
        return task

    def unregister(self, task_type: str) -> TaskFactory:
        """Remove and return the factory for ``task_type``.

        Raises:
            UnknownTaskTypeError: If the type has not been registered.
        """
        key = _normalize_type(task_type)
        try:
            return self._types.pop(key)
        except KeyError:
            raise UnknownTaskTypeError(
                f"Cannot unregister unknown task type '{key}'"
            ) from None

    def list_types(self) -> list[str]:
        """Return registered type names in sorted order."""
        return sorted(self._types)

    def __contains__(self, task_type: object) -> bool:
        if not isinstance(task_type, str):
            return False
        try:
            key = _normalize_type(task_type)
        except ValueError:
            return False
        return key in self._types

    def __len__(self) -> int:
        return len(self._types)

    def __iter__(self) -> Iterator[str]:
        return iter(self.list_types())


_default_registry = TaskRegistry()


def get_default_registry() -> TaskRegistry:
    """Return the process-wide default registry (includes built-in types)."""
    return _default_registry


def register(task_type: str, factory: TaskFactory) -> None:
    """Register a task type on the default registry."""
    _default_registry.register(task_type, factory)


def resolve(task_type: str) -> TaskFactory:
    """Resolve a task type from the default registry."""
    return _default_registry.resolve(task_type)


def create(task_type: str, *args, **kwargs) -> Task:
    """Create a task from the default registry."""
    return _default_registry.create(task_type, *args, **kwargs)


def unregister(task_type: str) -> TaskFactory:
    """Unregister a task type from the default registry."""
    return _default_registry.unregister(task_type)


def list_types() -> list[str]:
    """List task types on the default registry."""
    return _default_registry.list_types()

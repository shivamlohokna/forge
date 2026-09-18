"""Tests for Phase 7.1 Task Registry."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from forge.core.task import Task
from forge.exceptions import DuplicateTaskTypeError, UnknownTaskTypeError
from forge.registry import (
    BUILTIN_TASK_TYPES,
    TaskRegistry,
    create,
    get_default_registry,
    list_types,
    register,
    register_builtin_tasks,
    resolve,
    unregister,
)
from forge.tasks import FileTask, FunctionTask, HTTPTask, ShellTask

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _EchoTask(Task):
    def execute(self, context):
        return context.task_name


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class TestTaskRegistry:
    def test_register_and_resolve(self):
        registry = TaskRegistry()
        registry.register("echo", _EchoTask)
        assert registry.resolve("echo") is _EchoTask
        assert "echo" in registry

    def test_type_names_are_case_insensitive(self):
        registry = TaskRegistry()
        registry.register("Echo", _EchoTask)
        assert registry.resolve("ECHO") is _EchoTask
        assert registry.list_types() == ["echo"]

    def test_duplicate_registration_raises(self):
        registry = TaskRegistry()
        registry.register("echo", _EchoTask)
        with pytest.raises(DuplicateTaskTypeError, match="already registered"):
            registry.register("echo", _EchoTask)
        with pytest.raises(DuplicateTaskTypeError):
            registry.register("ECHO", FunctionTask)

    def test_unknown_type_raises(self):
        registry = TaskRegistry()
        with pytest.raises(UnknownTaskTypeError, match="Unknown task type"):
            registry.resolve("http")

    def test_unregister_returns_factory(self):
        registry = TaskRegistry()
        registry.register("echo", _EchoTask)
        factory = registry.unregister("echo")
        assert factory is _EchoTask
        assert "echo" not in registry
        with pytest.raises(UnknownTaskTypeError, match="Cannot unregister"):
            registry.unregister("echo")

    def test_list_types_sorted(self):
        registry = TaskRegistry()
        registry.register("zeta", _EchoTask)
        registry.register("alpha", _EchoTask)
        assert registry.list_types() == ["alpha", "zeta"]
        assert list(registry) == ["alpha", "zeta"]
        assert len(registry) == 2

    def test_empty_type_rejected(self):
        registry = TaskRegistry()
        with pytest.raises(ValueError, match="cannot be empty"):
            registry.register("  ", _EchoTask)

    def test_non_callable_factory_rejected(self):
        registry = TaskRegistry()
        with pytest.raises(TypeError, match="must be callable"):
            registry.register("broken", object())  # type: ignore[arg-type]

    def test_create_invokes_factory(self):
        registry = TaskRegistry()
        registry.register("echo", _EchoTask)
        task = registry.create("echo", name="ping")
        assert isinstance(task, _EchoTask)
        assert task.name == "ping"

    def test_create_rejects_non_task_return(self):
        registry = TaskRegistry()
        registry.register("bad", lambda **kwargs: "not a task")
        with pytest.raises(TypeError, match="must return a Task"):
            registry.create("bad")

    def test_isolated_registry_has_no_builtins(self):
        registry = TaskRegistry()
        assert registry.list_types() == []
        with pytest.raises(UnknownTaskTypeError):
            registry.resolve("http")


class TestBuiltinRegistration:
    def test_register_builtin_tasks_on_fresh_registry(self):
        registry = TaskRegistry()
        register_builtin_tasks(registry)
        assert registry.list_types() == ["file", "function", "http", "shell"]
        assert registry.resolve("function") is FunctionTask
        assert registry.resolve("file") is FileTask
        assert registry.resolve("shell") is ShellTask
        assert registry.resolve("http") is HTTPTask

    def test_register_builtin_tasks_is_idempotent(self):
        registry = TaskRegistry()
        register_builtin_tasks(registry)
        register_builtin_tasks(registry)
        assert registry.list_types() == ["file", "function", "http", "shell"]

    def test_builtin_map_matches_classes(self):
        assert BUILTIN_TASK_TYPES == {
            "function": FunctionTask,
            "file": FileTask,
            "shell": ShellTask,
            "http": HTTPTask,
        }

    def test_default_registry_includes_builtins(self):
        default = get_default_registry()
        assert default.resolve("http") is HTTPTask
        assert set(list_types()) == {"function", "file", "shell", "http"}

    def test_default_create_function_task(self):
        task = create("function", name="work", fn=lambda: 42)
        assert isinstance(task, FunctionTask)
        assert task.name == "work"

    def test_default_create_file_task(self):
        task = create("file", name="touch", operation="EXISTS", path=".")
        assert isinstance(task, FileTask)

    def test_default_create_shell_task(self):
        task = create("shell", name="echo", command="echo hi")
        assert isinstance(task, ShellTask)

    def test_default_create_http_task(self):
        task = create("http", name="ping", url="https://example.com")
        assert isinstance(task, HTTPTask)

    def test_module_level_register_unregister_roundtrip(self):
        assert "echo-custom" not in get_default_registry()
        try:
            register("echo-custom", _EchoTask)
            assert resolve("echo-custom") is _EchoTask
        finally:
            unregister("echo-custom")
        with pytest.raises(UnknownTaskTypeError):
            resolve("echo-custom")


class TestEngineUnawareOfRegistry:
    def test_engine_and_core_do_not_import_registry(self):
        core_dir = PROJECT_ROOT / "forge" / "core"
        for path in core_dir.glob("*.py"):
            modules = _imported_modules(path.read_text(encoding="utf-8"))
            offenders = [m for m in modules if "registry" in m.split(".")]
            assert not offenders, f"{path.name} imports registry: {offenders}"

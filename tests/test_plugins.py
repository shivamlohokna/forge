"""Unit tests for Phase 7.2 (Plugin Discovery) & Phase 7.3 (Plugin Lifecycle & Contracts) in Forge."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from forge.core.engine import Engine
from forge.core.task import ExecutionContext, Task
from forge.core.workflow import Workflow
from forge.exceptions import (
    DuplicateTaskTypeError,
    MalformedPluginError,
    PluginDiscoveryError,
    PluginError,
    PluginIncompatibleError,
    PluginLifecycleError,
    PluginLoadError,
)
from forge.plugins import (
    DEFAULT_ENTRY_POINT_GROUP,
    ForgePlugin,
    LoadedPluginInfo,
    PluginLoadReport,
    PluginManager,
    discover_plugins,
    load_plugin,
    load_plugins,
    validate_plugin,
)
from forge.registry.task_registry import TaskRegistry, get_default_registry


# ── Test Fixtures and Helpers ──────────────────────────────────────────────────

class DummyEntryPoint:
    """Mock importlib.metadata.EntryPoint for testing discovery and loading."""

    def __init__(
        self,
        name: str,
        value: str,
        target_obj: Any,
        group: str = DEFAULT_ENTRY_POINT_GROUP,
    ) -> None:
        self.name = name
        self.value = value
        self.group = group
        self._target_obj = target_obj

    def load(self) -> Any:
        if isinstance(self._target_obj, Exception):
            raise self._target_obj
        return self._target_obj


class CustomPluginTask(Task):
    """Custom task type contributed by a plugin for testing."""

    def __init__(self, multiplier: int = 2, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.multiplier = multiplier

    def execute(self, context: ExecutionContext) -> int:
        val = context.parameters.get("input_val", 10)
        return val * self.multiplier


class ValidTestPlugin:
    """Sample valid plugin implementation."""

    name = "test_math_plugin"
    version = "1.0.0"

    def register(self, registry: TaskRegistry) -> None:
        registry.register("math_custom", CustomPluginTask)


class ValidPluginB:
    """Second valid plugin implementation."""

    name = "test_plugin_b"
    version = "0.2.0"

    def register(self, registry: TaskRegistry) -> None:
        registry.register("task_b", CustomPluginTask)


class LifecyclePlugin:
    """Plugin with on_load and on_unload lifecycle hooks."""

    name = "lifecycle_plugin"
    version = "1.0.0"

    def __init__(self, task_type: str = "lifecycle_task") -> None:
        self.task_type = task_type
        self.loaded_called = False
        self.unloaded_called = False

    def on_load(self) -> None:
        self.loaded_called = True

    def register(self, registry: TaskRegistry) -> None:
        registry.register(self.task_type, CustomPluginTask)

    def on_unload(self) -> None:
        self.unloaded_called = True



class FaultyRegistrationPlugin:
    """Plugin that registers one task then raises an error mid-registration."""

    name = "faulty_plugin"

    def register(self, registry: TaskRegistry) -> None:
        registry.register("valid_type_1", CustomPluginTask)
        raise RuntimeError("Unexpected failure during registration!")


# ── Test Suite ─────────────────────────────────────────────────────────────────

def test_plugin_interface_validation_success():
    """Verify validate_plugin succeeds for compliant ForgePlugin objects."""
    plugin = ValidTestPlugin()
    validate_plugin(plugin)
    assert isinstance(plugin, ForgePlugin)


@pytest.mark.parametrize(
    "invalid_obj, error_match",
    [
        (None, "Loaded plugin object is None"),
        (object(), "missing required 'name' attribute"),
        (type("NoName", (), {})(), "missing required 'name' attribute"),
        (type("BadNameType", (), {"name": 12345})(), "Plugin 'name' must be a string"),
        (type("EmptyName", (), {"name": "   "})(), "Plugin 'name' cannot be empty"),
        (type("NoRegister", (), {"name": "valid"})(), "missing required 'register' method"),
        (type("NotCallableRegister", (), {"name": "valid", "register": "foo"})(), "must be callable"),
        (type("BadVersion", (), {"name": "v", "register": lambda r: None, "version": 123})(), "attribute 'version' must be a string"),
        (type("BadOnLoad", (), {"name": "v", "register": lambda r: None, "on_load": "not_fn"})(), "attribute 'on_load' must be callable"),
    ],
)
def test_malformed_plugin_rejection(invalid_obj: Any, error_match: str):
    """Verify malformed plugin objects are rejected with MalformedPluginError."""
    with pytest.raises(MalformedPluginError, match=error_match):
        validate_plugin(invalid_obj)


def test_discover_plugins_sorting():
    """Verify discover_plugins returns entry points deterministically sorted by name."""
    ep_z = DummyEntryPoint("z_plugin", "pkg.z:plugin", ValidTestPlugin())
    ep_a = DummyEntryPoint("a_plugin", "pkg.a:plugin", ValidPluginB())
    ep_m = DummyEntryPoint("m_plugin", "pkg.m:plugin", ValidTestPlugin())

    with patch("importlib.metadata.entry_points", return_value=[ep_z, ep_a, ep_m]):
        discovered = discover_plugins()

    assert len(discovered) == 3
    assert [ep.name for ep in discovered] == ["a_plugin", "m_plugin", "z_plugin"]


def test_load_plugin_success():
    """Verify load_plugin loads and validates a valid plugin entry point."""
    ep = DummyEntryPoint("test_ep", "pkg:ValidTestPlugin", ValidTestPlugin)
    plugin = load_plugin(ep)
    assert plugin.name == "test_math_plugin"


def test_load_plugin_import_failure():
    """Verify load_plugin converts import/load exceptions into PluginLoadError."""
    ep = DummyEntryPoint(
        "broken_ep", "pkg.broken:plugin", ImportError("No module named 'broken'")
    )
    with pytest.raises(PluginLoadError, match="Failed to load plugin entry point 'broken_ep'"):
        load_plugin(ep)


def test_load_plugins_registration_and_report():
    """Verify load_plugins loads entry points, registers task types, and returns report."""
    registry = TaskRegistry()
    ep1 = DummyEntryPoint("ep1", "pkg1:plugin", ValidTestPlugin())

    with patch("importlib.metadata.entry_points", return_value=[ep1]):
        report = load_plugins(registry)

    assert isinstance(report, PluginLoadReport)
    assert report.total_plugins == 1
    assert "math_custom" in registry
    assert report.registered_task_types == ["math_custom"]
    assert report.loaded_plugins[0].plugin_name == "test_math_plugin"


def test_multiple_plugins_registration():
    """Verify multiple plugins can register distinct task types into one registry."""
    registry = TaskRegistry()
    ep1 = DummyEntryPoint("ep1", "pkg1:plugin", ValidTestPlugin())
    ep2 = DummyEntryPoint("ep2", "pkg2:plugin", ValidPluginB())

    with patch("importlib.metadata.entry_points", return_value=[ep1, ep2]):
        report = load_plugins(registry)

    assert report.total_plugins == 2
    assert "math_custom" in registry
    assert "task_b" in registry
    assert sorted(report.registered_task_types) == ["math_custom", "task_b"]


def test_duplicate_task_type_rejection():
    """Verify registering duplicate task types across plugins raises DuplicateTaskTypeError."""
    registry = TaskRegistry()
    registry.register("math_custom", CustomPluginTask)

    ep1 = DummyEntryPoint("ep1", "pkg1:plugin", ValidTestPlugin())

    with patch("importlib.metadata.entry_points", return_value=[ep1]):
        with pytest.raises(DuplicateTaskTypeError, match="Task type 'math_custom' is already registered"):
            load_plugins(registry)


def test_custom_task_execution_through_engine():
    """Verify a plugin-registered task executes seamlessly through the existing Engine."""
    registry = TaskRegistry()
    plugin = ValidTestPlugin()
    plugin.register(registry)

    # Create task instance via registry
    task_instance = registry.create("math_custom", name="multiplier_task", multiplier=3)

    workflow = Workflow(name="plugin_workflow")
    workflow.add_task(task_instance)

    engine = Engine(verbose=False)
    result = engine.run(workflow, parameters={"input_val": 7})

    assert result.is_success
    assert result.get_task_result("multiplier_task").output == 21


def test_registry_isolation():
    """Verify loading plugins into one registry does not pollute other registries or default registry."""
    reg_isolated = TaskRegistry()
    reg_other = TaskRegistry()

    ep1 = DummyEntryPoint("ep1", "pkg1:plugin", ValidTestPlugin())

    with patch("importlib.metadata.entry_points", return_value=[ep1]):
        load_plugins(reg_isolated)

    assert "math_custom" in reg_isolated
    assert "math_custom" not in reg_other
    assert "math_custom" not in get_default_registry()


def test_default_builtin_registry_remains_intact():
    """Verify default registry contains all built-in types and is untouched by plugin operations."""
    default_reg = get_default_registry()
    builtins = ["function", "http", "shell", "file"]
    for b in builtins:
        assert b in default_reg


def test_engine_remains_unaware_of_plugins():
    """Verify engine module does not import or depend on forge.plugins or forge.registry."""
    import forge.core.engine as engine_mod

    module_content = open(engine_mod.__file__, encoding="utf-8").read()
    assert "forge.plugins" not in module_content
    assert "forge.registry" not in module_content
    assert "TaskRegistry" not in module_content


# ── Phase 7.3 Specific Tests ───────────────────────────────────────────────────

def test_version_compatibility_checks():
    """Verify min_forge_version enforcement allows compatible plugins and rejects incompatible ones."""
    compatible_plugin = type("Comp", (), {"name": "c", "register": lambda r: None, "min_forge_version": "0.1.0"})()
    validate_plugin(compatible_plugin)

    incompatible_plugin = type("Incomp", (), {"name": "ic", "register": lambda r: None, "min_forge_version": "99.0.0"})()
    with pytest.raises(PluginIncompatibleError, match="requires Forge version >= 99.0.0"):
        validate_plugin(incompatible_plugin)


def test_lifecycle_hooks_on_load_and_on_unload():
    """Verify on_load and on_unload hooks are invoked during plugin manager lifecycle."""
    registry = TaskRegistry()
    manager = PluginManager(registry)
    plugin = LifecyclePlugin()

    assert not plugin.loaded_called
    assert not plugin.unloaded_called

    manager.register_plugin(plugin)
    assert plugin.loaded_called
    assert "lifecycle_task" in registry
    assert manager.is_loaded("lifecycle_plugin")

    unregistered = manager.unload_plugin("lifecycle_plugin")
    assert unregistered == ["lifecycle_task"]
    assert plugin.unloaded_called
    assert "lifecycle_task" not in registry
    assert not manager.is_loaded("lifecycle_plugin")


def test_transactional_rollback_on_registration_failure():
    """Verify atomic rollback removes partial task type registrations if plugin.register() fails."""
    registry = TaskRegistry()
    manager = PluginManager(registry)
    faulty_plugin = FaultyRegistrationPlugin()

    before_types = set(registry.list_types())

    with pytest.raises(RuntimeError, match="Unexpected failure during registration"):
        manager.register_plugin(faulty_plugin)

    # Registry must be completely restored to before_types (no orphaned 'valid_type_1')
    after_types = set(registry.list_types())
    assert after_types == before_types
    assert "valid_type_1" not in registry
    assert not manager.is_loaded("faulty_plugin")


def test_plugin_manager_unload_all():
    """Verify PluginManager.unload_all unloads all loaded plugins in reverse order."""
    registry = TaskRegistry()
    manager = PluginManager(registry)

    plugin1 = LifecyclePlugin(task_type="p1_task")
    plugin1.name = "p1"
    plugin2 = LifecyclePlugin(task_type="p2_task")
    plugin2.name = "p2"

    manager.register_plugin(plugin1)
    manager.register_plugin(plugin2)

    assert manager.list_plugins() == ["p1", "p2"]

    manager.unload_all()
    assert manager.list_plugins() == []
    assert plugin1.unloaded_called
    assert plugin2.unloaded_called
    assert "p1_task" not in registry
    assert "p2_task" not in registry



def test_on_load_failure_handling():
    """Verify on_load failure prevents registration and raises PluginLifecycleError."""
    registry = TaskRegistry()
    manager = PluginManager(registry)

    class BrokenOnLoadPlugin:
        name = "broken_on_load"
        def on_load(self) -> None:
            raise ValueError("Configuration missing!")
        def register(self, reg: TaskRegistry) -> None:
            reg.register("should_not_exist", CustomPluginTask)

    plugin = BrokenOnLoadPlugin()
    with pytest.raises(PluginLifecycleError, match="on_load\\(\\) lifecycle hook failed"):
        manager.register_plugin(plugin)

    assert "should_not_exist" not in registry
    assert not manager.is_loaded("broken_on_load")


def test_on_unload_failure_handling():
    """Verify on_unload failure raises PluginLifecycleError but task types are still unregistered."""
    registry = TaskRegistry()
    manager = PluginManager(registry)

    class BrokenOnUnloadPlugin:
        name = "broken_on_unload"
        def register(self, reg: TaskRegistry) -> None:
            reg.register("temp_type", CustomPluginTask)
        def on_unload(self) -> None:
            raise RuntimeError("Cleanup failed!")

    plugin = BrokenOnUnloadPlugin()
    manager.register_plugin(plugin)
    assert "temp_type" in registry

    with pytest.raises(PluginLifecycleError, match="on_unload\\(\\) lifecycle hook failed"):
        manager.unload_plugin("broken_on_unload")

    # Task type should still be unregistered despite unload hook exception
    assert "temp_type" not in registry
    assert not manager.is_loaded("broken_on_unload")

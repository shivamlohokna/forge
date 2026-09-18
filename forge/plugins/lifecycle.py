"""Plugin lifecycle and state management for Forge.

Provides the PluginManager for safe, transactional loading, state tracking,
and clean unloading of plugins without leaving orphaned registry state.
"""

from __future__ import annotations

import logging
from typing import Any

from forge.exceptions import (
    DuplicateTaskTypeError,
    PluginError,
    PluginLifecycleError,
)
from forge.plugins.interface import ForgePlugin, validate_plugin
from forge.registry.task_registry import TaskRegistry

logger = logging.getLogger("forge.plugins.lifecycle")


class PluginManager:
    """Manages active plugins, lifecycle hooks, and transactional task registrations.

    Args:
        registry: Target TaskRegistry receiving task type registrations.
    """

    def __init__(self, registry: TaskRegistry) -> None:
        if not isinstance(registry, TaskRegistry):
            raise TypeError(
                f"registry must be a TaskRegistry instance, got {type(registry).__name__}"
            )
        self.registry: TaskRegistry = registry
        self._loaded_plugins: dict[str, ForgePlugin] = {}
        self._plugin_task_types: dict[str, set[str]] = {}

    def is_loaded(self, plugin_name: str) -> bool:
        """Check if a plugin with ``plugin_name`` is currently loaded."""
        return plugin_name in self._loaded_plugins

    def get_plugin(self, plugin_name: str) -> ForgePlugin:
        """Retrieve loaded plugin object by name.

        Raises:
            PluginError: If plugin is not loaded.
        """
        try:
            return self._loaded_plugins[plugin_name]
        except KeyError:
            raise PluginError(f"Plugin '{plugin_name}' is not loaded.") from None

    def list_plugins(self) -> list[str]:
        """Return names of all currently loaded plugins in loading order."""
        return list(self._loaded_plugins.keys())

    def register_plugin(self, plugin: Any) -> list[str]:
        """Validate, execute on_load(), and register task types atomically.

        Args:
            plugin: Object implementing ForgePlugin contract.

        Returns:
            List of newly registered task type names.

        Raises:
            MalformedPluginError: If plugin fails contract validation.
            PluginIncompatibleError: If plugin is incompatible with current Forge version.
            PluginLifecycleError: If on_load() hook fails.
            DuplicateTaskTypeError: If plugin registers an already registered task type.
            PluginError: If plugin name is already loaded.
        """
        validate_plugin(plugin)

        if plugin.name in self._loaded_plugins:
            raise DuplicateTaskTypeError(
                f"Plugin with name '{plugin.name}' is already loaded in this PluginManager."
            )

        # 1. Execute optional `on_load()` lifecycle hook
        if hasattr(plugin, "on_load") and callable(getattr(plugin, "on_load")):
            try:
                plugin.on_load()
            except Exception as exc:
                raise PluginLifecycleError(
                    f"Plugin '{plugin.name}' on_load() lifecycle hook failed: {exc}"
                ) from exc

        # 2. Register task types atomically into TaskRegistry
        before_types = set(self.registry.list_types())
        try:
            plugin.register(self.registry)
        except Exception as exc:
            # Atomic Rollback: remove any task types registered during the failed call
            after_types = set(self.registry.list_types())
            newly_added = after_types - before_types
            for task_type in newly_added:
                try:
                    self.registry.unregister(task_type)
                except Exception as rollback_err:
                    logger.warning(
                        "Failed to rollback task type '%s' for plugin '%s': %s",
                        task_type,
                        plugin.name,
                        rollback_err,
                    )
            raise

        after_types = set(self.registry.list_types())
        new_types = sorted(after_types - before_types)

        # 3. Track active plugin state
        self._loaded_plugins[plugin.name] = plugin
        self._plugin_task_types[plugin.name] = set(new_types)

        return new_types

    def unload_plugin(self, plugin_name: str) -> list[str]:
        """Unregister all task types for ``plugin_name`` and execute on_unload().

        Args:
            plugin_name: Identity name of the plugin to unload.

        Returns:
            List of task type names unregistered.

        Raises:
            PluginError: If plugin is not loaded.
            PluginLifecycleError: If on_unload() hook fails.
        """
        if plugin_name not in self._loaded_plugins:
            raise PluginError(f"Cannot unload: Plugin '{plugin_name}' is not loaded.")

        plugin = self._loaded_plugins.pop(plugin_name)
        task_types = self._plugin_task_types.pop(plugin_name, set())

        unregistered: list[str] = []
        for task_type in sorted(task_types):
            if task_type in self.registry:
                try:
                    self.registry.unregister(task_type)
                    unregistered.append(task_type)
                except Exception as unreg_err:
                    logger.warning(
                        "Error unregistering task type '%s' during unload of '%s': %s",
                        task_type,
                        plugin_name,
                        unreg_err,
                    )

        # Execute optional `on_unload()` lifecycle hook
        if hasattr(plugin, "on_unload") and callable(getattr(plugin, "on_unload")):
            try:
                plugin.on_unload()
            except Exception as exc:
                raise PluginLifecycleError(
                    f"Plugin '{plugin_name}' on_unload() lifecycle hook failed: {exc}"
                ) from exc

        return unregistered

    def unload_all(self) -> dict[str, list[str]]:
        """Unload all active plugins in reverse load order.

        Returns:
            Dict mapping plugin names to lists of unregistered task types.
        """
        results = {}
        for plugin_name in list(reversed(self.list_plugins())):
            results[plugin_name] = self.unload_plugin(plugin_name)
        return results

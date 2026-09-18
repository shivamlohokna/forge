"""Plugin discovery and loading machinery for Forge.

Discovers plugin entry points from installed Python packages, validates their
contract, and registers their task types into a caller-supplied TaskRegistry.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
from typing import TYPE_CHECKING, Any

from forge.exceptions import (
    DuplicateTaskTypeError,
    MalformedPluginError,
    PluginDiscoveryError,
    PluginIncompatibleError,
    PluginLifecycleError,
    PluginLoadError,
)
from forge.plugins.interface import ForgePlugin, validate_plugin
from forge.plugins.lifecycle import PluginManager
from forge.registry.task_registry import TaskRegistry

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint

DEFAULT_ENTRY_POINT_GROUP = "forge.plugins"


@dataclass(frozen=True)
class LoadedPluginInfo:
    """Information about a successfully loaded plugin and its registered task types."""

    plugin_name: str
    entry_point_name: str
    registered_task_types: list[str]


@dataclass(frozen=True)
class PluginLoadReport:
    """Summary report returned after loading plugins into a registry."""

    loaded_plugins: list[LoadedPluginInfo]

    @property
    def total_plugins(self) -> int:
        """Total number of plugins successfully loaded."""
        return len(self.loaded_plugins)

    @property
    def registered_task_types(self) -> list[str]:
        """All task type names registered across all loaded plugins, sorted."""
        types: set[str] = set()
        for info in self.loaded_plugins:
            types.update(info.registered_task_types)
        return sorted(types)


def discover_plugins(group: str = DEFAULT_ENTRY_POINT_GROUP) -> list[EntryPoint]:
    """Discover Forge plugin entry points from installed Python packages.

    Args:
        group: The packaging entry point group to query. Defaults to ``"forge.plugins"``.

    Returns:
        List of EntryPoint objects, sorted deterministically by (name, value).

    Raises:
        PluginDiscoveryError: If entry point discovery encounters an unrecoverable failure.
    """
    try:
        eps = importlib.metadata.entry_points()
        if hasattr(eps, "select"):
            group_eps = list(eps.select(group=group))
        elif hasattr(eps, "get"):
            group_eps = list(eps.get(group, []))
        else:
            group_eps = [ep for ep in eps if getattr(ep, "group", None) == group]
    except Exception as exc:
        raise PluginDiscoveryError(f"Failed to discover plugin entry points: {exc}") from exc

    return sorted(group_eps, key=lambda ep: (getattr(ep, "name", ""), getattr(ep, "value", "")))


def load_plugin(entry_point: Any) -> ForgePlugin:
    """Load and validate a single plugin entry point.

    Args:
        entry_point: The packaging EntryPoint object to load.

    Returns:
        The loaded and validated ForgePlugin object.

    Raises:
        PluginLoadError: If loading or instantiating the entry point fails.
        MalformedPluginError: If the loaded object violates the plugin contract.
        PluginIncompatibleError: If the plugin requires a newer version of Forge.
    """
    ep_name = getattr(entry_point, "name", "<unknown>")
    try:
        loaded = entry_point.load()
    except Exception as exc:
        raise PluginLoadError(
            f"Failed to load plugin entry point '{ep_name}': {exc}"
        ) from exc

    plugin_obj = loaded
    if isinstance(loaded, type):
        try:
            plugin_obj = loaded()
        except Exception as exc:
            raise PluginLoadError(
                f"Failed to instantiate plugin class '{loaded.__name__}' "
                f"from entry point '{ep_name}': {exc}"
            ) from exc

    validate_plugin(plugin_obj)
    return plugin_obj


def load_plugins(
    registry: TaskRegistry,
    group: str = DEFAULT_ENTRY_POINT_GROUP,
) -> PluginLoadReport:
    """Discover, load, and register all plugin entry points into ``registry``.

    Args:
        registry: Target TaskRegistry to receive task type registrations.
        group: Packaging entry point group to discover. Defaults to ``"forge.plugins"``.

    Returns:
        PluginLoadReport with details on loaded plugins and registered task types.

    Raises:
        TypeError: If ``registry`` is not a TaskRegistry instance.
        DuplicateTaskTypeError: If a plugin attempts to register an existing task type.
        PluginLoadError: If loading a plugin entry point fails.
        MalformedPluginError: If a loaded plugin violates the contract.
        PluginIncompatibleError: If a plugin requires an incompatible version of Forge.
        PluginLifecycleError: If a plugin on_load() hook fails.
    """
    if not isinstance(registry, TaskRegistry):
        raise TypeError(
            f"registry must be a TaskRegistry instance, got {type(registry).__name__}"
        )

    manager = PluginManager(registry)
    entry_points = discover_plugins(group=group)
    loaded_infos: list[LoadedPluginInfo] = []

    for ep in entry_points:
        plugin = load_plugin(ep)
        try:
            new_types = manager.register_plugin(plugin)
        except (
            DuplicateTaskTypeError,
            PluginIncompatibleError,
            MalformedPluginError,
            PluginLifecycleError,
        ):
            raise
        except Exception as exc:
            raise PluginLoadError(
                f"Plugin '{plugin.name}' raised an error during task registration: {exc}"
            ) from exc

        loaded_infos.append(
            LoadedPluginInfo(
                plugin_name=plugin.name,
                entry_point_name=getattr(ep, "name", ""),
                registered_task_types=new_types,
            )
        )

    return PluginLoadReport(loaded_plugins=loaded_infos)

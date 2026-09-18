"""Forge Plugin Subsystem.

Provides explicit discovery, contract validation, lifecycle management, and
loading of task type plugins via standard Python packaging entry points.
"""

from forge.exceptions import (
    MalformedPluginError,
    PluginDiscoveryError,
    PluginError,
    PluginIncompatibleError,
    PluginLifecycleError,
    PluginLoadError,
)
from forge.plugins.discovery import (
    DEFAULT_ENTRY_POINT_GROUP,
    LoadedPluginInfo,
    PluginLoadReport,
    discover_plugins,
    load_plugin,
    load_plugins,
)
from forge.plugins.interface import ForgePlugin, validate_plugin
from forge.plugins.lifecycle import PluginManager

__all__ = [
    "DEFAULT_ENTRY_POINT_GROUP",
    "ForgePlugin",
    "LoadedPluginInfo",
    "MalformedPluginError",
    "PluginDiscoveryError",
    "PluginError",
    "PluginIncompatibleError",
    "PluginLifecycleError",
    "PluginLoadError",
    "PluginLoadReport",
    "PluginManager",
    "discover_plugins",
    "load_plugin",
    "load_plugins",
    "validate_plugin",
]

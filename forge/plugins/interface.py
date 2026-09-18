"""Forge task plugin interface and validation logic.

Defines the explicit plugin contract using standard Python Protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import forge
from forge.exceptions import MalformedPluginError, PluginIncompatibleError
from forge.registry.task_registry import TaskRegistry


@runtime_checkable
class ForgePlugin(Protocol):
    """Protocol defining the Forge Task Plugin contract.

    Required:
        name: Non-empty string uniquely identifying the plugin.
        register(registry): Method registering task types into a target TaskRegistry.

    Optional:
        version: Semantic version string (e.g., "0.1.0").
        min_forge_version: Minimum required Forge version string (e.g., "0.2.0").
        on_load(): Optional hook executed after plugin loading & validation.
        on_unload(): Optional hook executed when the plugin is unloaded.
    """

    name: str

    def register(self, registry: TaskRegistry) -> None:
        """Register task types into the provided TaskRegistry."""
        ...


def _parse_version(ver_str: str) -> tuple[int, ...]:
    """Parse version string into a tuple of integers for comparison."""
    parts = []
    for part in ver_str.strip().split("."):
        digits = "".join(c for c in part if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def validate_plugin(obj: Any) -> None:
    """Validate that ``obj`` satisfies the ``ForgePlugin`` contract and version requirements.

    Args:
        obj: The object loaded from a plugin entry point.

    Raises:
        MalformedPluginError: If ``obj`` fails contract validation.
        PluginIncompatibleError: If ``obj`` requires a newer version of Forge.
    """
    if obj is None:
        raise MalformedPluginError("Loaded plugin object is None.")

    # 1. Validate `name`
    if not hasattr(obj, "name"):
        raise MalformedPluginError(
            f"Plugin object {obj!r} is missing required 'name' attribute."
        )

    name = getattr(obj, "name")
    if not isinstance(name, str):
        raise MalformedPluginError(
            f"Plugin 'name' must be a string, got {type(name).__name__} ({name!r})."
        )

    if not name.strip():
        raise MalformedPluginError("Plugin 'name' cannot be empty or whitespace.")

    # 2. Validate `version` (optional, must be string if present)
    if hasattr(obj, "version") and getattr(obj, "version") is not None:
        version = getattr(obj, "version")
        if not isinstance(version, str):
            raise MalformedPluginError(
                f"Plugin '{name}' attribute 'version' must be a string, got {type(version).__name__}."
            )

    # 3. Validate `register`
    if not hasattr(obj, "register"):
        raise MalformedPluginError(
            f"Plugin '{name}' is missing required 'register' method."
        )

    register_fn = getattr(obj, "register")
    if not callable(register_fn):
        raise MalformedPluginError(
            f"Plugin '{name}' attribute 'register' must be callable, "
            f"got {type(register_fn).__name__}."
        )

    # 4. Validate optional lifecycle hooks
    if hasattr(obj, "on_load") and getattr(obj, "on_load") is not None:
        if not callable(getattr(obj, "on_load")):
            raise MalformedPluginError(
                f"Plugin '{name}' attribute 'on_load' must be callable, "
                f"got {type(getattr(obj, 'on_load')).__name__}."
            )

    if hasattr(obj, "on_unload") and getattr(obj, "on_unload") is not None:
        if not callable(getattr(obj, "on_unload")):
            raise MalformedPluginError(
                f"Plugin '{name}' attribute 'on_unload' must be callable, "
                f"got {type(getattr(obj, 'on_unload')).__name__}."
            )

    # 5. Check version compatibility (`min_forge_version`)
    if hasattr(obj, "min_forge_version") and getattr(obj, "min_forge_version") is not None:
        min_ver = getattr(obj, "min_forge_version")
        if not isinstance(min_ver, str):
            raise MalformedPluginError(
                f"Plugin '{name}' attribute 'min_forge_version' must be a string, got {type(min_ver).__name__}."
            )

        current_ver = getattr(forge, "__version__", "0.0.0")
        if _parse_version(current_ver) < _parse_version(min_ver):
            raise PluginIncompatibleError(
                f"Plugin '{name}' requires Forge version >= {min_ver}, but current version is {current_ver}."
            )

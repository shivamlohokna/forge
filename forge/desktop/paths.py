"""Per-user application data directory and resource resolution for Forge Desktop."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_app_data_dir() -> Path:
    """Return the platform-appropriate per-user application data directory.

    On Windows: %APPDATA%/Forge
    On macOS:   ~/Library/Application Support/Forge
    On Linux:   ~/.local/share/forge or $XDG_DATA_HOME/forge
    """
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base = Path(app_data)
        else:
            base = Path.home() / "AppData" / "Roaming"
        return base / "Forge"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Forge"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            return Path(xdg_data) / "forge"
        return Path.home() / ".local" / "share" / "forge"


def get_workflows_dir() -> Path:
    """Return the directory where user workflow specifications are stored."""
    return get_app_data_dir() / "workflows"


def get_database_path() -> Path:
    """Return the default SQLite persistence database path for desktop runs."""
    return get_app_data_dir() / "forge.db"


def get_logs_dir() -> Path:
    """Return the desktop logs directory."""
    return get_app_data_dir() / "logs"


def ensure_app_directories() -> None:
    """Ensure that all necessary user data directories exist."""
    get_app_data_dir().mkdir(parents=True, exist_ok=True)
    get_workflows_dir().mkdir(parents=True, exist_ok=True)
    get_logs_dir().mkdir(parents=True, exist_ok=True)


def get_icon_path(fmt: str = "png") -> Path:
    """Locate the bundled application icon (supports PyInstaller frozen bundles)."""
    # Check if running in a PyInstaller bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = Path(sys._MEIPASS)
        candidate = base_dir / "forge" / "resources" / "icons" / f"forge.{fmt}"
        if candidate.exists():
            return candidate
        candidate = base_dir / "resources" / "icons" / f"forge.{fmt}"
        if candidate.exists():
            return candidate

    # Standard package location
    pkg_dir = Path(__file__).resolve().parent.parent
    candidate = pkg_dir / "resources" / "icons" / f"forge.{fmt}"
    if candidate.exists():
        return candidate

    # Fallback to current working directory
    return Path.cwd() / "forge" / "resources" / "icons" / f"forge.{fmt}"

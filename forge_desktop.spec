# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Forge Desktop.

Produces a single-directory Windows executable bundle containing:
- The Forge engine, CLI, persistence, and desktop GUI
- PySide6 runtime libraries
- Application icon and bundled resources
"""

import os
import sys
from pathlib import Path

block_cipher = None

REPO_ROOT = Path(SPECPATH)
FORGE_PKG = REPO_ROOT / "forge"
ICON_ICO = str(FORGE_PKG / "resources" / "icons" / "forge.ico")
ICON_PNG = str(FORGE_PKG / "resources" / "icons" / "forge.png")

# Collect all forge subpackages
a = Analysis(
    [str(REPO_ROOT / "forge_gui.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[
        (str(FORGE_PKG / "resources"), "forge/resources"),
        (str(FORGE_PKG / "py.typed"), "forge"),
    ],
    hiddenimports=[
        "forge",
        "forge.core",
        "forge.core.engine",
        "forge.core.task",
        "forge.core.workflow",
        "forge.core.executor",
        "forge.core.events",
        "forge.core.result",
        "forge.core.output",
        "forge.core.conditions",
        "forge.cli",
        "forge.cli.main",
        "forge.cli.commands",
        "forge.cli.loader",
        "forge.config",
        "forge.config.loader",
        "forge.config.model",
        "forge.declarative",
        "forge.declarative.loader",
        "forge.declarative.validator",
        "forge.declarative.spec",
        "forge.declarative.interpolation",
        "forge.declarative.parameters",
        "forge.declarative.parsers",
        "forge.exceptions",
        "forge.logging",
        "forge.persistence",
        "forge.persistence.store",
        "forge.persistence.schema",
        "forge.persistence.models",
        "forge.plugins",
        "forge.registry",
        "forge.registry.task_registry",
        "forge.registry.builtins",
        "forge.tasks",
        "forge.utils",
        "forge.utils.sanitizer",
        "forge.utils.pid",
        "forge.desktop",
        "forge.desktop.main_window",
        "forge.desktop.paths",
        "forge.desktop.runner",
        "forge.desktop.styles",
        "forge.desktop.templates",
        "forge.desktop.views",
        "forge.desktop.views.home_view",
        "forge.desktop.views.editor_view",
        "forge.desktop.views.workflows_view",
        "forge.desktop.views.history_view",
        "forge.desktop.views.settings_view",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "PIL",
        "cv2",
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtMultimedia",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtWebSockets",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ForgeDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI application — no terminal window
    icon=ICON_ICO,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ForgeDesktop",
)

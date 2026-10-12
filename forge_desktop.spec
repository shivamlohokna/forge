# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Forge Desktop — cross-platform.

Produces:
  Windows : single-directory bundle (dist/ForgeDesktop/) using .ico icon
  macOS   : .app bundle (dist/ForgeDesktop.app) using .icns/.png icon
  Linux   : single-directory bundle (dist/ForgeDesktop/) using .png icon

Run with:
  pyinstaller --noconfirm forge_desktop.spec
"""

import sys
from pathlib import Path

block_cipher = None

REPO_ROOT = Path(SPECPATH)
FORGE_PKG  = REPO_ROOT / "forge"
ICON_ICO   = str(FORGE_PKG / "resources" / "icons" / "forge.ico")
ICON_PNG   = str(FORGE_PKG / "resources" / "icons" / "forge.png")
ICON_ICNS  = str(FORGE_PKG / "resources" / "icons" / "forge.icns")

# Resolve per-platform icon
if sys.platform == "darwin":
    _icon = ICON_ICNS if Path(ICON_ICNS).exists() else ICON_PNG
elif sys.platform == "win32":
    _icon = ICON_ICO
else:
    _icon = ICON_PNG

# Shared hidden imports for all forge subpackages
_hidden = [
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
]

_excludes = [
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
]

# Analysis — Windows-only flags omitted on non-Windows to avoid warnings
_analysis_kwargs = dict(
    scripts=[str(REPO_ROOT / "forge_gui.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[
        (str(FORGE_PKG / "resources"), "forge/resources"),
        (str(FORGE_PKG / "py.typed"),  "forge"),
    ],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    cipher=block_cipher,
    noarchive=False,
)
if sys.platform == "win32":
    _analysis_kwargs["win_no_prefer_redirects"] = False
    _analysis_kwargs["win_private_assemblies"]   = False

a = Analysis(**_analysis_kwargs)

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
    console=False,   # windowless on all platforms
    icon=_icon,
    disable_windowed_traceback=False,
)

# ── macOS: produce a .app bundle ────────────────────────────────────────────
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        name="ForgeDesktop.app",
        icon=_icon,
        bundle_identifier="io.github.shivamlohokna.forge",
        info_plist={
            "CFBundleName":               "Forge",
            "CFBundleDisplayName":        "Forge Desktop",
            "CFBundleVersion":            "0.3.0",
            "CFBundleShortVersionString": "0.3.0",
            "CFBundleIdentifier":         "io.github.shivamlohokna.forge",
            "CFBundleExecutable":         "ForgeDesktop",
            "CFBundleIconFile":           "forge",
            "NSPrincipalClass":           "NSApplication",
            "NSHighResolutionCapable":    True,
            "NSHumanReadableCopyright":   "Copyright © 2026 Forge Project. Apache-2.0.",
            "LSMinimumSystemVersion":     "12.0",
            "NSRequiresAquaSystemAppearance": False,
        },
        strip=False,
        upx=False,
    )

# ── Windows & Linux: produce a directory bundle (COLLECT) ────────────────────
else:
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

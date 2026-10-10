"""Forge Desktop main window — sidebar navigation shell."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from forge.desktop.paths import ensure_app_directories, get_icon_path
from forge.desktop.styles import (
    BACKGROUND_DARK,
    MAIN_STYLESHEET,
    PRIMARY,
    SURFACE_DARK,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from forge.desktop.views.editor_view import WorkflowEditorView
from forge.desktop.views.history_view import HistoryView
from forge.desktop.views.home_view import HomeView
from forge.desktop.views.settings_view import SettingsView
from forge.desktop.views.workflows_view import WorkflowsView


class ForgeMainWindow(QWidget):
    """Main application window with sidebar navigation and stacked content area."""

    def __init__(self) -> None:
        super().__init__()
        ensure_app_directories()
        self.setWindowTitle("Forge — Workflow Automation")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 780)

        # Set window icon
        icon_path = get_icon_path("png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._init_ui()

    def _init_ui(self) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("sidebarFrame")
        sidebar.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 20, 12, 20)
        sidebar_layout.setSpacing(4)

        # Logo / Brand
        brand_label = QLabel("⚡ Forge")
        brand_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {TEXT_PRIMARY};"
            f"padding: 8px 4px 16px 4px; letter-spacing: 0.5px;"
        )
        sidebar_layout.addWidget(brand_label)

        # Navigation buttons
        self._nav_buttons: list[QPushButton] = []

        nav_items = [
            ("🏠  Home", "home"),
            ("📋  Workflows", "workflows"),
            ("✏️  Editor", "editor"),
            ("📈  Run History", "history"),
            ("⚙️  Settings", "settings"),
        ]

        for label, key in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setProperty("navKey", key)
            btn.clicked.connect(self._on_nav_click)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sidebar_layout.addStretch()

        # Version badge at bottom of sidebar
        version_lbl = QLabel("v0.2.0")
        version_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; padding: 4px;")
        sidebar_layout.addWidget(version_lbl)

        root_layout.addWidget(sidebar)

        # ── Content Stack ─────────────────────────────────────────────────────
        self._stack = QStackedWidget()

        self.home_view = HomeView()
        self.workflows_view = WorkflowsView()
        self.editor_view = WorkflowEditorView()
        self.history_view = HistoryView()
        self.settings_view = SettingsView()

        self._stack.addWidget(self.home_view)         # index 0
        self._stack.addWidget(self.workflows_view)    # index 1
        self._stack.addWidget(self.editor_view)       # index 2
        self._stack.addWidget(self.history_view)      # index 3
        self._stack.addWidget(self.settings_view)     # index 4

        root_layout.addWidget(self._stack)

        # ── Signal Wiring ─────────────────────────────────────────────────────
        self.home_view.sig_create_new.connect(self._on_create_new)
        self.home_view.sig_open_workflow.connect(self._on_open_workflow_file)
        self.home_view.sig_view_history.connect(lambda: self._navigate_to("history"))
        self.home_view.sig_use_template.connect(self._on_use_template)

        self.workflows_view.sig_open_workflow.connect(self._on_open_workflow)
        self.workflows_view.sig_create_new.connect(self._on_create_new)

        self.editor_view.sig_run_completed.connect(self._on_run_completed)

        # ── Set initial view ──────────────────────────────────────────────────
        self._navigate_to("home")

    def _navigate_to(self, key: str) -> None:
        """Activate a sidebar nav item by its key."""
        key_to_index = {
            "home": 0,
            "workflows": 1,
            "editor": 2,
            "history": 3,
            "settings": 4,
        }
        idx = key_to_index.get(key, 0)
        self._stack.setCurrentIndex(idx)

        for btn in self._nav_buttons:
            btn.setChecked(btn.property("navKey") == key)

        # Refresh live data when navigating
        if key == "home":
            self.home_view.refresh_metrics()
        elif key == "workflows":
            self.workflows_view.refresh_workflows()
        elif key == "history":
            self.history_view.refresh_history()

    def _on_nav_click(self) -> None:
        btn = self.sender()
        if btn:
            key = btn.property("navKey")
            self._navigate_to(key)

    def _on_create_new(self) -> None:
        """Switch to Editor with a blank workflow."""
        blank: dict[str, Any] = {
            "name": "My New Workflow",
            "description": "Describe what this workflow does",
            "max_workers": 4,
            "tasks": [],
        }
        self.editor_view.set_workflow(blank)
        self._navigate_to("editor")

    def _on_use_template(self, workflow_dict: dict[str, Any]) -> None:
        """Open a starter template in the Editor."""
        self.editor_view.set_workflow(workflow_dict)
        self._navigate_to("editor")

    def _on_open_workflow(self, workflow_dict: dict[str, Any], file_path: Any) -> None:
        """Open a workflow from the Workflows view into the Editor."""
        path = Path(file_path) if file_path else None
        self.editor_view.set_workflow(workflow_dict, file_path=path)
        self._navigate_to("editor")

    def _on_open_workflow_file(self) -> None:
        """Open a file chooser dialog from the Home view."""
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open Workflow File",
            str(Path.home()),
            "Workflow Files (*.json *.toml *.yaml *.yml);;All Files (*.*)",
        )
        if not file_path_str:
            return
        path = Path(file_path_str)
        try:
            from forge.declarative.parsers import parse_workflow_file
            data = parse_workflow_file(path)
            self.editor_view.set_workflow(data, file_path=path)
            self._navigate_to("editor")
        except Exception as err:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Open Error", f"Failed to load workflow:\n{err}")

    def _on_run_completed(self, run_id: str) -> None:
        """Refresh history when a run finishes."""
        self.history_view.refresh_history()
        self.home_view.refresh_metrics()

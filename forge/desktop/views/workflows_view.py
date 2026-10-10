"""Workflows view listing saved and imported workflow files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from forge.declarative.loader import parse_workflow_file
from forge.desktop.paths import get_workflows_dir
from forge.desktop.styles import DANGER, PRIMARY, SURFACE_CARD, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY


class WorkflowsView(QWidget):
    """Lists saved workflows with open, delete, import, and run actions."""

    sig_open_workflow = Signal(dict, object) # workflow_dict, file_path
    sig_create_new = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Saved Workflows")
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {TEXT_PRIMARY};")
        header.addWidget(title)
        header.addStretch()

        import_btn = QPushButton("Import File...")
        import_btn.setObjectName("secondaryBtn")
        import_btn.clicked.connect(self._on_import_file)
        header.addWidget(import_btn)

        new_btn = QPushButton("+ New Workflow")
        new_btn.setObjectName("primaryBtn")
        new_btn.clicked.connect(self.sig_create_new.emit)
        header.addWidget(new_btn)

        layout.addLayout(header)

        # Workflows Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Workflow Name", "File", "Tasks", "Last Modified"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemDoubleClicked.connect(self._on_open_selected)
        layout.addWidget(self.table)

        # Action Buttons
        actions_layout = QHBoxLayout()
        open_btn = QPushButton("Open in Editor")
        open_btn.setObjectName("primaryBtn")
        open_btn.clicked.connect(self._on_open_selected)
        actions_layout.addWidget(open_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.refresh_workflows)
        actions_layout.addWidget(refresh_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("dangerBtn")
        delete_btn.clicked.connect(self._on_delete_selected)
        actions_layout.addWidget(delete_btn)

        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        self.loaded_files: list[Path] = []
        self.refresh_workflows()

    def refresh_workflows(self) -> None:
        """Scan workflows directory and populate table."""
        wf_dir = get_workflows_dir()
        wf_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(list(wf_dir.glob("*.json")), key=lambda p: p.stat().st_mtime, reverse=True)
        self.loaded_files = files

        self.table.setRowCount(len(files))
        for row, path in enumerate(files):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                name = data.get("name", path.stem)
                tasks_cnt = len(data.get("tasks", []))
            except Exception:
                name = path.stem
                tasks_cnt = 0

            mtime_str = Path(path).stat().st_mtime
            import datetime
            time_formatted = datetime.datetime.fromtimestamp(mtime_str).strftime("%Y-%m-%d %H:%M")

            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(path.name))
            self.table.setItem(row, 2, QTableWidgetItem(str(tasks_cnt)))
            self.table.setItem(row, 3, QTableWidgetItem(time_formatted))

    def _on_open_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.loaded_files):
            return
        path = self.loaded_files[row]
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.sig_open_workflow.emit(data, path)
        except Exception as err:
            QMessageBox.critical(self, "Read Error", f"Failed to load workflow file: {err}")

    def _on_delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.loaded_files):
            return
        path = self.loaded_files[row]
        reply = QMessageBox.question(
            self,
            "Delete Workflow",
            f"Are you sure you want to permanently delete '{path.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                path.unlink()
                self.refresh_workflows()
            except Exception as err:
                QMessageBox.critical(self, "Delete Error", f"Could not delete workflow: {err}")

    def _on_import_file(self) -> None:
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Workflow Specification",
            str(Path.home()),
            "Workflow Files (*.json *.toml *.yaml *.yml);;All Files (*.*)",
        )
        if not file_path_str:
            return

        import_path = Path(file_path_str)
        try:
            data = parse_workflow_file(import_path)
            self.sig_open_workflow.emit(data, import_path)
        except Exception as err:
            QMessageBox.critical(self, "Import Error", f"Failed to parse workflow file:\n{err}")

"""Interactive Workflow Editor and Live Execution Dashboard."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from forge.declarative.loader import load_declarative_workflow
from forge.declarative.validator import validate_workflow_dict
from forge.desktop.paths import get_database_path, get_workflows_dir
from forge.desktop.runner import WorkflowRunnerThread
from forge.desktop.styles import (
    DANGER,
    INFO,
    PRIMARY,
    SUCCESS,
    SURFACE_CARD,
    SURFACE_DARK,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)
from forge.exceptions import WorkflowSpecError
from forge.registry.task_registry import get_default_registry
from forge.utils.sanitizer import sanitize, sanitize_error


class TaskEditDialog(QDialog):
    """Form dialog to add or edit a task in the workflow."""

    def __init__(
        self,
        existing_task: dict[str, Any] | None = None,
        available_dependencies: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure Task" if existing_task else "Add New Task")
        self.setMinimumWidth(540)
        self.existing_task = existing_task or {}
        self.available_deps = [d for d in (available_dependencies or []) if d != self.existing_task.get("name")]
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)

        # Task Name
        self.name_edit = QLineEdit(self.existing_task.get("name", ""))
        self.name_edit.setPlaceholderText("e.g. build_artifact, query_status")
        form.addRow("Task Name*:", self.name_edit)

        # Task Type
        self.type_combo = QComboBox()
        self.type_combo.addItems(["shell", "file", "http"])
        cur_type = self.existing_task.get("type", "shell").lower()
        idx = self.type_combo.findText(cur_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Task Type*:", self.type_combo)

        # Failure Strategy
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["STOP", "CONTINUE", "SKIP", "RETRY"])
        cur_strat = self.existing_task.get("failure_strategy", "STOP").upper()
        s_idx = self.strategy_combo.findText(cur_strat)
        if s_idx >= 0:
            self.strategy_combo.setCurrentIndex(s_idx)
        form.addRow("Failure Strategy:", self.strategy_combo)

        # Dependencies
        self.deps_edit = QLineEdit(", ".join(self.existing_task.get("depends_on", [])))
        self.deps_edit.setPlaceholderText(f"Comma-separated list (available: {', '.join(self.available_deps) or 'none'})")
        form.addRow("Depends On:", self.deps_edit)

        layout.addLayout(form)

        # Type-specific parameters widget
        self.params_frame = QFrame()
        self.params_frame.setObjectName("cardFrame")
        self.params_layout = QFormLayout(self.params_frame)
        layout.addWidget(self.params_frame)

        # Unpack params if present
        params = self.existing_task.get("params", {})

        # Shell inputs
        cmd_val = self.existing_task.get("command", params.get("command", ""))
        self.cmd_edit = QPlainTextEdit(cmd_val)
        self.cmd_edit.setPlaceholderText("powershell -Command \"...\" or command line string")
        self.cmd_edit.setMaximumHeight(80)

        cwd_val = self.existing_task.get("working_directory", params.get("working_directory", ""))
        self.cwd_edit = QLineEdit(cwd_val)
        self.cwd_edit.setPlaceholderText("Leave empty for current directory")

        # File inputs
        self.file_action_combo = QComboBox()
        self.file_action_combo.addItems(["write", "read", "copy", "move", "delete"])
        cur_act = self.existing_task.get("operation", self.existing_task.get("action", params.get("operation", params.get("action", "write")))).lower()
        fa_idx = self.file_action_combo.findText(cur_act)
        if fa_idx >= 0:
            self.file_action_combo.setCurrentIndex(fa_idx)

        path_val = self.existing_task.get("path", params.get("path", ""))
        self.file_path_edit = QLineEdit(path_val)
        dest_val = self.existing_task.get("destination", params.get("destination", ""))
        self.file_dest_edit = QLineEdit(dest_val)
        content_val = self.existing_task.get("content", params.get("content", ""))
        self.file_content_edit = QPlainTextEdit(content_val)
        self.file_content_edit.setMaximumHeight(80)

        # HTTP inputs
        self.http_method_combo = QComboBox()
        self.http_method_combo.addItems(["GET", "POST", "PUT", "DELETE"])
        cur_hm = self.existing_task.get("method", params.get("method", "GET")).upper()
        hm_idx = self.http_method_combo.findText(cur_hm)
        if hm_idx >= 0:
            self.http_method_combo.setCurrentIndex(hm_idx)

        url_val = self.existing_task.get("url", params.get("url", ""))
        self.http_url_edit = QLineEdit(url_val)
        self.http_url_edit.setPlaceholderText("https://api.example.com/health")
        self.http_status_spin = QSpinBox()
        self.http_status_spin.setRange(100, 599)
        self.http_status_spin.setValue(self.existing_task.get("expected_status", params.get("expected_status", 200)))

        self._refresh_type_fields()

        # Dialog Buttons
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bbox.accepted.connect(self._validate_and_accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _on_type_changed(self) -> None:
        self._refresh_type_fields()

    def _refresh_type_fields(self) -> None:
        # Clear params layout
        while self.params_layout.count() > 0:
            item = self.params_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        task_type = self.type_combo.currentText()
        if task_type == "shell":
            self.params_layout.addRow("Shell Command*:", self.cmd_edit)
            self.params_layout.addRow("Working Dir:", self.cwd_edit)
        elif task_type == "file":
            self.params_layout.addRow("File Action*:", self.file_action_combo)
            self.params_layout.addRow("File Path*:", self.file_path_edit)
            self.params_layout.addRow("Destination:", self.file_dest_edit)
            self.params_layout.addRow("Content (write):", self.file_content_edit)
        elif task_type == "http":
            self.params_layout.addRow("HTTP Method*:", self.http_method_combo)
            self.params_layout.addRow("URL*:", self.http_url_edit)
            self.params_layout.addRow("Expected Status:", self.http_status_spin)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Task", "Task name is required.")
            return

        task_type = self.type_combo.currentText()
        if task_type == "shell" and not self.cmd_edit.toPlainText().strip():
            QMessageBox.warning(self, "Invalid Task", "Shell command is required.")
            return
        elif task_type == "file" and not self.file_path_edit.text().strip():
            QMessageBox.warning(self, "Invalid Task", "File path is required.")
            return
        elif task_type == "http" and not self.http_url_edit.text().strip():
            QMessageBox.warning(self, "Invalid Task", "HTTP URL is required.")
            return

        self.accept()

    def get_task_dict(self) -> dict[str, Any]:
        """Construct the task definition dictionary."""
        name = self.name_edit.text().strip()
        task_type = self.type_combo.currentText()
        strat = self.strategy_combo.currentText()

        deps_raw = [d.strip() for d in self.deps_edit.text().split(",") if d.strip()]

        params: dict[str, Any] = {}
        if task_type == "shell":
            params["command"] = self.cmd_edit.toPlainText().strip()
            if self.cwd_edit.text().strip():
                params["working_directory"] = self.cwd_edit.text().strip()
        elif task_type == "file":
            params["operation"] = self.file_action_combo.currentText().lower()
            params["path"] = self.file_path_edit.text().strip()
            if self.file_dest_edit.text().strip():
                params["destination"] = self.file_dest_edit.text().strip()
            if self.file_content_edit.toPlainText().strip():
                params["content"] = self.file_content_edit.toPlainText()
        elif task_type == "http":
            params["method"] = self.http_method_combo.currentText()
            params["url"] = self.http_url_edit.text().strip()
            params["expected_status"] = self.http_status_spin.value()

        data: dict[str, Any] = {
            "id": name,
            "name": name,
            "type": task_type,
            "failure_strategy": strat,
            "params": params,
        }
        if deps_raw:
            data["depends_on"] = deps_raw

        return data


class WorkflowEditorView(QWidget):
    """Full-featured workflow creator, editor, validator, and runner."""

    sig_run_completed = Signal(str)  # run_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_workflow_path: Path | None = None
        self.runner_thread: WorkflowRunnerThread | None = None
        self.active_run_id: str = ""
        self._elapsed_seconds: float = 0.0
        self._timer: QTimer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # Header bar
        header_layout = QHBoxLayout()
        self.header_lbl = QLabel("Workflow Editor")
        self.header_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {TEXT_PRIMARY};")
        header_layout.addWidget(self.header_lbl)

        header_layout.addStretch()

        self.validate_btn = QPushButton("✓ Validate")
        self.validate_btn.setObjectName("secondaryBtn")
        self.validate_btn.clicked.connect(self.validate_workflow)
        header_layout.addWidget(self.validate_btn)

        self.save_btn = QPushButton("Save Workflow")
        self.save_btn.setObjectName("secondaryBtn")
        self.save_btn.clicked.connect(self.save_workflow)
        header_layout.addWidget(self.save_btn)

        self.run_btn = QPushButton("▶ Run Workflow")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.clicked.connect(self.run_workflow)
        header_layout.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("⏹ Cancel Run")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_run)
        header_layout.addWidget(self.cancel_btn)

        main_layout.addLayout(header_layout)

        # Validation status banner
        self.status_banner = QLabel("Ready to configure tasks and execute.")
        self.status_banner.setStyleSheet(f"background-color: {SURFACE_CARD}; padding: 8px 14px; border-radius: 6px; color: {TEXT_SECONDARY};")
        main_layout.addWidget(self.status_banner)

        # Main splitter (Editor on left, Live execution on right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # --- LEFT PANEL: Workflow Structure ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)

        # Workflow Metadata
        meta_frame = QFrame()
        meta_frame.setObjectName("cardFrame")
        meta_form = QFormLayout(meta_frame)
        meta_form.setSpacing(8)

        self.wf_name_edit = QLineEdit("My Workflow")
        meta_form.addRow("Workflow Name*:", self.wf_name_edit)

        self.wf_desc_edit = QLineEdit("Automated task sequence")
        meta_form.addRow("Description:", self.wf_desc_edit)

        self.wf_workers_spin = QSpinBox()
        self.wf_workers_spin.setRange(1, 16)
        self.wf_workers_spin.setValue(4)
        meta_form.addRow("Max Workers:", self.wf_workers_spin)

        left_layout.addWidget(meta_frame)

        # Task Management Section
        tasks_header = QHBoxLayout()
        tasks_title = QLabel("Workflow Tasks (DAG)")
        tasks_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT_PRIMARY};")
        tasks_header.addWidget(tasks_title)
        tasks_header.addStretch()

        add_task_btn = QPushButton("+ Add Task")
        add_task_btn.setObjectName("secondaryBtn")
        add_task_btn.clicked.connect(self._on_add_task)
        tasks_header.addWidget(add_task_btn)
        left_layout.addLayout(tasks_header)

        # Task Table
        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["Task Name", "Type", "Depends On", "Strategy"])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.itemDoubleClicked.connect(self._on_edit_task)
        left_layout.addWidget(self.task_table)

        # Task Table Actions
        task_actions = QHBoxLayout()
        edit_task_btn = QPushButton("Edit Selected")
        edit_task_btn.setObjectName("secondaryBtn")
        edit_task_btn.clicked.connect(self._on_edit_task)
        task_actions.addWidget(edit_task_btn)

        del_task_btn = QPushButton("Remove Task")
        del_task_btn.setObjectName("secondaryBtn")
        del_task_btn.clicked.connect(self._on_remove_task)
        task_actions.addWidget(del_task_btn)

        task_actions.addStretch()
        left_layout.addLayout(task_actions)

        splitter.addWidget(left_widget)

        # --- RIGHT PANEL: Live Execution & Telemetry ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)

        # Execution Status Card
        exec_card = QFrame()
        exec_card.setObjectName("cardFrame")
        exec_card_layout = QHBoxLayout(exec_card)

        self.status_pill = QLabel("IDLE")
        self.status_pill.setObjectName("badgePending")
        exec_card_layout.addWidget(self.status_pill)

        self.run_info_lbl = QLabel("No active execution.")
        self.run_info_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        exec_card_layout.addWidget(self.run_info_lbl)

        exec_card_layout.addStretch()
        self.elapsed_lbl = QLabel("0.0s")
        self.elapsed_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600; font-size: 14px;")
        exec_card_layout.addWidget(self.elapsed_lbl)

        right_layout.addWidget(exec_card)

        # Tabs for Live Tasks & Logs
        tabs = QTabWidget()

        # Tab 1: Live Task Progress Table
        self.live_task_table = QTableWidget(0, 4)
        self.live_task_table.setHorizontalHeaderLabels(["Task", "Status", "Duration", "Summary / Error"])
        self.live_task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.live_task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.live_task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.live_task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        tabs.addTab(self.live_task_table, "Live Tasks")

        # Tab 2: Execution Console Logs
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet(
            f"background-color: {SURFACE_DARK}; color: #38BDF8; font-family: monospace; font-size: 12px;"
        )
        tabs.addTab(self.log_console, "Execution Logs")

        right_layout.addWidget(tabs)
        splitter.addWidget(right_widget)

        splitter.setSizes([450, 450])
        main_layout.addWidget(splitter)

        self.tasks_data: list[dict[str, Any]] = []

    @staticmethod
    def _normalize_task_dict(t: dict[str, Any]) -> dict[str, Any]:
        task = dict(t)
        tid = str(task.get("id") or task.get("name") or "task").strip()
        task["id"] = tid
        task["name"] = str(task.get("name") or tid).strip()
        params = dict(task.get("params", {}))
        for k in ["command", "working_directory", "path", "source", "destination", "content", "url", "method", "expected_status"]:
            if k in task and k not in params:
                params[k] = task[k]
        if "action" in task and "operation" not in params:
            params["operation"] = str(task["action"]).lower()
        elif "operation" in task and "operation" not in params:
            params["operation"] = str(task["operation"]).lower()
        task["params"] = params
        return task

    def set_workflow(self, workflow_dict: dict[str, Any], file_path: Path | None = None) -> None:
        """Populate the editor with a workflow dictionary."""
        self.current_workflow_path = file_path
        self.wf_name_edit.setText(workflow_dict.get("name", "New Workflow"))
        self.wf_desc_edit.setText(workflow_dict.get("description", ""))
        self.wf_workers_spin.setValue(int(workflow_dict.get("max_workers", 4)))
        self.tasks_data = [self._normalize_task_dict(t) for t in workflow_dict.get("tasks", [])]
        self._refresh_task_table()
        self.status_banner.setText(f"Loaded workflow: {workflow_dict.get('name')}")
        self.status_banner.setStyleSheet(f"background-color: {SURFACE_CARD}; color: {TEXT_PRIMARY}; padding: 8px 14px; border-radius: 6px;")

    def get_workflow_dict(self) -> dict[str, Any]:
        """Construct the complete declarative workflow dict from editor state."""
        return {
            "name": self.wf_name_edit.text().strip() or "Unnamed Workflow",
            "description": self.wf_desc_edit.text().strip(),
            "max_workers": self.wf_workers_spin.value(),
            "tasks": [self._normalize_task_dict(t) for t in self.tasks_data],
        }

    def _refresh_task_table(self) -> None:
        self.task_table.setRowCount(len(self.tasks_data))
        for row, t in enumerate(self.tasks_data):
            self.task_table.setItem(row, 0, QTableWidgetItem(t.get("name", "")))
            self.task_table.setItem(row, 1, QTableWidgetItem(t.get("type", "").upper()))
            deps = ", ".join(t.get("depends_on", []))
            self.task_table.setItem(row, 2, QTableWidgetItem(deps or "-"))
            self.task_table.setItem(row, 3, QTableWidgetItem(t.get("failure_strategy", "STOP")))

    def _on_add_task(self) -> None:
        existing_names = [t["name"] for t in self.tasks_data]
        dlg = TaskEditDialog(available_dependencies=existing_names, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.tasks_data.append(dlg.get_task_dict())
            self._refresh_task_table()
            self.validate_workflow()

    def _on_edit_task(self) -> None:
        selected_row = self.task_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.tasks_data):
            return
        task = self.tasks_data[selected_row]
        existing_names = [t["name"] for t in self.tasks_data]
        dlg = TaskEditDialog(existing_task=task, available_dependencies=existing_names, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.tasks_data[selected_row] = dlg.get_task_dict()
            self._refresh_task_table()
            self.validate_workflow()

    def _on_remove_task(self) -> None:
        selected_row = self.task_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.tasks_data):
            return
        del self.tasks_data[selected_row]
        self._refresh_task_table()
        self.validate_workflow()

    def validate_workflow(self) -> bool:
        """Validate workflow using existing Forge declarative validation engine."""
        data = self.get_workflow_dict()
        if not data["tasks"]:
            self.status_banner.setText("Validation Warning: Workflow contains no tasks.")
            self.status_banner.setStyleSheet(f"background-color: #78350F; color: #FDE047; padding: 8px 14px; border-radius: 6px;")
            return False

        try:
            registry = get_default_registry()
            validate_workflow_dict(data, registry=registry)
            wf = load_declarative_workflow(data, registry=registry)
            batches = wf.get_execution_batches()
            msg = f"✓ Workflow Valid: {len(wf.tasks)} tasks, {len(batches)} topological execution batches."
            self.status_banner.setText(msg)
            self.status_banner.setStyleSheet(f"background-color: #064E3B; color: #6EE7B7; padding: 8px 14px; border-radius: 6px;")
            return True
        except (WorkflowSpecError, Exception) as err:
            clean_err = sanitize_error(str(err)) or "Validation failed"
            self.status_banner.setText(f"✕ Invalid Workflow: {clean_err}")
            self.status_banner.setStyleSheet(f"background-color: #7F1D1D; color: #FCA5A5; padding: 8px 14px; border-radius: 6px;")
            return False

    def save_workflow(self, prompt_if_invalid: bool = True) -> bool:
        """Save workflow JSON to user-data storage directory."""
        if not self.validate_workflow():
            if prompt_if_invalid:
                resp = QMessageBox.question(
                    self,
                    "Save Unvalidated Workflow?",
                    "The workflow currently has validation warnings or errors. Do you still want to save it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if resp != QMessageBox.StandardButton.Yes:
                    return False
            else:
                return False

        data = self.get_workflow_dict()
        name = data["name"]
        safe_filename = re.sub(r"[^\w\-]", "_", name).lower() + ".json"

        if not self.current_workflow_path:
            workflows_dir = get_workflows_dir()
            workflows_dir.mkdir(parents=True, exist_ok=True)
            self.current_workflow_path = workflows_dir / safe_filename

        try:
            with open(self.current_workflow_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.status_banner.setText(f"Saved workflow to {self.current_workflow_path.name}")
            self.status_banner.setStyleSheet(f"background-color: #064E3B; color: #6EE7B7; padding: 8px 14px; border-radius: 6px;")
            return True
        except Exception as err:
            QMessageBox.critical(self, "Save Error", f"Failed to save workflow: {err}")
            return False

    def run_workflow(self) -> None:
        """Run workflow through existing Forge engine in the background."""
        if not self.validate_workflow():
            QMessageBox.critical(self, "Cannot Run Workflow", "Please correct validation errors before executing.")
            return

        data = self.get_workflow_dict()

        # Security Confirmation for Shell Tasks
        shell_tasks = [t for t in data["tasks"] if t.get("type") == "shell"]
        if shell_tasks:
            cmds_preview = "\n".join(f"  • [{t['name']}] {t.get('command', '')}" for t in shell_tasks[:5])
            msg = (
                f"Security Notice: This workflow will execute {len(shell_tasks)} local shell command(s):\n\n"
                f"{cmds_preview}\n\n"
                "Shell commands run with your user account privileges. Are you sure you want to proceed?"
            )
            reply = QMessageBox.warning(
                self,
                "Confirm Shell Command Execution",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Prepare UI for live run
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_pill.setText("RUNNING")
        self.status_pill.setStyleSheet(f"background-color: #0C4A6E; color: {INFO}; border-radius: 4px; padding: 3px 8px; font-weight: 700;")
        self.run_info_lbl.setText("Executing workflow DAG...")
        self.log_console.clear()

        # Setup live task table
        self.live_task_table.setRowCount(len(data["tasks"]))
        self._task_row_map: dict[str, int] = {}
        for row, t in enumerate(data["tasks"]):
            t_name = t["name"]
            self._task_row_map[t_name] = row
            self.live_task_table.setItem(row, 0, QTableWidgetItem(t_name))
            self.live_task_table.setItem(row, 1, QTableWidgetItem("PENDING"))
            self.live_task_table.setItem(row, 2, QTableWidgetItem("-"))
            self.live_task_table.setItem(row, 3, QTableWidgetItem("-"))

        # Setup timer
        self._elapsed_seconds = 0.0
        self.elapsed_lbl.setText("0.0s")
        self._timer.start(100)

        # Spawn background execution worker
        db_path = get_database_path()
        self.runner_thread = WorkflowRunnerThread(
            workflow_spec_or_path=data,
            max_workers=data.get("max_workers", 4),
            db_path=db_path,
        )

        self.runner_thread.signals.sig_started.connect(self._on_run_started)
        self.runner_thread.signals.sig_task_started.connect(self._on_task_started)
        self.runner_thread.signals.sig_task_succeeded.connect(self._on_task_succeeded)
        self.runner_thread.signals.sig_task_failed.connect(self._on_task_failed)
        self.runner_thread.signals.sig_task_skipped.connect(self._on_task_skipped)
        self.runner_thread.signals.sig_log_emitted.connect(self._on_log_emitted)
        self.runner_thread.signals.sig_finished.connect(self._on_run_finished)
        self.runner_thread.signals.sig_error.connect(self._on_run_error)

        self.runner_thread.start()

    def cancel_run(self) -> None:
        """Cancel ongoing workflow run."""
        if self.runner_thread and self.runner_thread.isRunning():
            self.runner_thread.cancel()
            self.cancel_btn.setEnabled(False)
            self.run_info_lbl.setText("Cancellation requested...")

    def _on_timer_tick(self) -> None:
        self._elapsed_seconds += 0.1
        self.elapsed_lbl.setText(f"{self._elapsed_seconds:.1f}s")

    def _on_run_started(self, run_id: str, wf_name: str) -> None:
        self.active_run_id = run_id
        self.run_info_lbl.setText(f"Run ID: {run_id[:16]}... ({wf_name})")

    def _on_task_started(self, task_name: str, attempt: int) -> None:
        row = self._task_row_map.get(task_name)
        if row is not None:
            self.live_task_table.setItem(row, 1, QTableWidgetItem(f"RUNNING (att {attempt})"))
            self.live_task_table.item(row, 1).setForeground(Qt.GlobalColor.cyan)

    def _on_task_succeeded(self, task_name: str, summary: str, duration: float) -> None:
        row = self._task_row_map.get(task_name)
        if row is not None:
            self.live_task_table.setItem(row, 1, QTableWidgetItem("SUCCESS"))
            self.live_task_table.item(row, 1).setForeground(Qt.GlobalColor.green)
            self.live_task_table.setItem(row, 2, QTableWidgetItem(f"{duration:.2f}s"))
            self.live_task_table.setItem(row, 3, QTableWidgetItem(summary))

    def _on_task_failed(self, task_name: str, error_msg: str, duration: float) -> None:
        row = self._task_row_map.get(task_name)
        if row is not None:
            self.live_task_table.setItem(row, 1, QTableWidgetItem("FAILED"))
            self.live_task_table.item(row, 1).setForeground(Qt.GlobalColor.red)
            self.live_task_table.setItem(row, 2, QTableWidgetItem(f"{duration:.2f}s"))
            self.live_task_table.setItem(row, 3, QTableWidgetItem(error_msg))

    def _on_task_skipped(self, task_name: str, reason: str) -> None:
        row = self._task_row_map.get(task_name)
        if row is not None:
            self.live_task_table.setItem(row, 1, QTableWidgetItem("SKIPPED"))
            self.live_task_table.item(row, 1).setForeground(Qt.GlobalColor.yellow)
            self.live_task_table.setItem(row, 3, QTableWidgetItem(reason))

    def _on_log_emitted(self, level: str, msg: str) -> None:
        self.log_console.appendPlainText(f"[{level}] {msg}")

    def _on_run_finished(self, is_success: bool, run_id: str, duration: float, summary: dict[str, Any]) -> None:
        self._timer.stop()
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        status_str = summary.get("status", "SUCCESS" if is_success else "FAILED")
        if is_success:
            self.status_pill.setText("SUCCESS")
            self.status_pill.setStyleSheet(f"background-color: #064E3B; color: {SUCCESS}; border-radius: 4px; padding: 3px 8px; font-weight: 700;")
        else:
            self.status_pill.setText(status_str)
            self.status_pill.setStyleSheet(f"background-color: #7F1D1D; color: {DANGER}; border-radius: 4px; padding: 3px 8px; font-weight: 700;")

        self.run_info_lbl.setText(
            f"Run finished in {duration:.2f}s • {summary.get('successful_tasks', 0)}/{summary.get('total_tasks', 0)} tasks passed"
        )
        self.sig_run_completed.emit(run_id)

    def _on_run_error(self, err_msg: str) -> None:
        self._timer.stop()
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_pill.setText("ERROR")
        self.status_pill.setStyleSheet(f"background-color: #7F1D1D; color: {DANGER}; border-radius: 4px; padding: 3px 8px; font-weight: 700;")
        self.run_info_lbl.setText(err_msg)
        QMessageBox.critical(self, "Workflow Execution Error", err_msg)

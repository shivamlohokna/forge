"""History view showing past workflow execution runs."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from forge.desktop.paths import get_database_path
from forge.desktop.styles import (
    DANGER,
    INFO,
    SUCCESS,
    SURFACE_CARD,
    SURFACE_DARK,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)
from forge.persistence.store import ExecutionStore


_STATUS_COLORS = {
    "SUCCESS": SUCCESS,
    "FAILED": DANGER,
    "CANCELLED": WARNING,
    "RUNNING": INFO,
}


class HistoryView(QWidget):
    """Displays paginated run history and per-run task detail."""

    sig_inspect_run = Signal(str)  # run_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all_runs: list[Any] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Execution History")
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {TEXT_PRIMARY};")
        header.addWidget(title)
        header.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.refresh_history)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        # Splitter: runs table | run detail
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Runs Table
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.runs_table = QTableWidget(0, 5)
        self.runs_table.setHorizontalHeaderLabels(["Run ID", "Workflow", "Status", "Duration", "Started"])
        self.runs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.runs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.runs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.runs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.runs_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.runs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.runs_table.itemSelectionChanged.connect(self._on_run_selection_changed)
        left_layout.addWidget(self.runs_table)

        splitter.addWidget(left)

        # Run Detail Panel
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        detail_title = QLabel("Run Details")
        detail_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT_PRIMARY};")
        right_layout.addWidget(detail_title)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("cardFrame")
        detail_card_layout = QVBoxLayout(self.detail_card)

        self.detail_run_id = QLabel("No run selected")
        self.detail_run_id.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-family: monospace;")
        detail_card_layout.addWidget(self.detail_run_id)

        self.detail_status = QLabel("-")
        self.detail_status.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TEXT_PRIMARY};")
        detail_card_layout.addWidget(self.detail_status)

        self.detail_metrics = QLabel("-")
        self.detail_metrics.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        detail_card_layout.addWidget(self.detail_metrics)

        right_layout.addWidget(self.detail_card)

        # Task Results Table
        tasks_label = QLabel("Task Results")
        tasks_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT_PRIMARY};")
        right_layout.addWidget(tasks_label)

        self.tasks_table = QTableWidget(0, 4)
        self.tasks_table.setHorizontalHeaderLabels(["Task", "Status", "Duration", "Output / Error"])
        self.tasks_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.tasks_table)

        splitter.addWidget(right)
        splitter.setSizes([380, 520])
        layout.addWidget(splitter)

        # Empty state
        self.empty_label = QLabel("No runs found. Execute a workflow to see history here.")
        self.empty_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px; padding: 40px;")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        self.refresh_history()

    def refresh_history(self) -> None:
        """Reload run history from the persistence store."""
        db_path = get_database_path()
        if not db_path.exists():
            self.runs_table.setRowCount(0)
            self.empty_label.show()
            return

        try:
            store = ExecutionStore.create(db_path)
            runs = store.list_workflow_runs(limit=200)
        except Exception:
            runs = []

        self._all_runs = runs
        self.runs_table.setRowCount(len(runs))

        if not runs:
            self.empty_label.show()
        else:
            self.empty_label.hide()

        for row, run in enumerate(runs):
            short_id = run.run_id[:12] + "..."
            self.runs_table.setItem(row, 0, QTableWidgetItem(short_id))
            self.runs_table.setItem(row, 1, QTableWidgetItem(run.workflow_name or "-"))
            status_item = QTableWidgetItem(run.status)
            color = _STATUS_COLORS.get(run.status, TEXT_SECONDARY)
            self.runs_table.setItem(row, 2, status_item)
            dur = f"{run.duration_seconds:.2f}s" if run.duration_seconds else "-"
            self.runs_table.setItem(row, 3, QTableWidgetItem(dur))
            started = (run.started_at or "-")[:19].replace("T", " ")
            self.runs_table.setItem(row, 4, QTableWidgetItem(started))

    def _on_run_selection_changed(self) -> None:
        row = self.runs_table.currentRow()
        self._on_run_selected(row)

    def _on_run_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._all_runs):
            return
        run = self._all_runs[row]
        self.detail_run_id.setText(f"Run ID: {run.run_id}")
        color = _STATUS_COLORS.get(run.status, TEXT_SECONDARY)
        self.detail_status.setText(run.status)
        self.detail_status.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color};")
        metrics = (
            f"Workflow: {run.workflow_name}  •  "
            f"Total: {run.total_tasks or 0}  •  "
            f"Passed: {run.success_count or 0}  •  "
            f"Failed: {run.failed_count or 0}  •  "
            f"Duration: {run.duration_seconds:.2f}s" if run.duration_seconds else
            f"Workflow: {run.workflow_name}"
        )
        self.detail_metrics.setText(metrics)

        # Load task results
        try:
            db_path = get_database_path()
            store = ExecutionStore.create(db_path)
            task_runs = store.get_task_runs(run.run_id)
        except Exception:
            task_runs = []

        self.tasks_table.setRowCount(len(task_runs))
        for tr_row, tr in enumerate(task_runs):
            self.tasks_table.setItem(tr_row, 0, QTableWidgetItem(tr.task_name))
            self.tasks_table.setItem(tr_row, 1, QTableWidgetItem(tr.status))
            dur_s = f"{tr.duration_seconds:.2f}s" if tr.duration_seconds else "-"
            self.tasks_table.setItem(tr_row, 2, QTableWidgetItem(dur_s))
            summary = tr.error_message or (str(tr.output)[:80] if tr.output else "-")
            self.tasks_table.setItem(tr_row, 3, QTableWidgetItem(summary))

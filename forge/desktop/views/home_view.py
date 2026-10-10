"""Home view presenting overview, quick actions, metrics, and starter templates."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from forge.desktop.paths import get_database_path, get_workflows_dir
from forge.desktop.styles import PRIMARY, SURFACE_CARD, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY
from forge.desktop.templates import STARTER_TEMPLATES
from forge.persistence.store import ExecutionStore


class HomeView(QWidget):
    """Main dashboard welcoming users and guiding them to workflows."""

    sig_create_new = Signal()
    sig_open_workflow = Signal()
    sig_view_history = Signal()
    sig_use_template = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(24)

        # 1. Hero Section
        hero_frame = QFrame()
        hero_frame.setObjectName("cardFrame")
        hero_layout = QVBoxLayout(hero_frame)
        hero_layout.setSpacing(10)

        title_lbl = QLabel("Forge Workflow Automation")
        title_lbl.setStyleSheet(f"font-size: 24px; font-weight: 700; color: {TEXT_PRIMARY};")
        hero_layout.addWidget(title_lbl)

        sub_lbl = QLabel(
            "Design, validate, and execute directed acyclic graphs (DAGs) of tasks with parallel execution, "
            "durable SQLite persistence, and graceful error recovery."
        )
        sub_lbl.setStyleSheet(f"font-size: 14px; color: {TEXT_SECONDARY}; line-height: 1.4;")
        sub_lbl.setWordWrap(True)
        hero_layout.addWidget(sub_lbl)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        new_btn = QPushButton("+ Create New Workflow")
        new_btn.setObjectName("primaryBtn")
        new_btn.clicked.connect(self.sig_create_new.emit)
        btn_layout.addWidget(new_btn)

        open_btn = QPushButton("Open Workflow File...")
        open_btn.setObjectName("secondaryBtn")
        open_btn.clicked.connect(self.sig_open_workflow.emit)
        btn_layout.addWidget(open_btn)

        history_btn = QPushButton("View Run History")
        history_btn.setObjectName("secondaryBtn")
        history_btn.clicked.connect(self.sig_view_history.emit)
        btn_layout.addWidget(history_btn)

        btn_layout.addStretch()
        hero_layout.addLayout(btn_layout)
        layout.addWidget(hero_frame)

        # 2. Status & Metric Badges
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(16)

        self.wf_count_lbl = self._create_metric_card("Saved Workflows", "0", "In local user storage")
        metrics_layout.addWidget(self.wf_count_lbl)

        self.runs_count_lbl = self._create_metric_card("Historical Runs", "0", "Persisted in SQLite database")
        metrics_layout.addWidget(self.runs_count_lbl)

        db_path = get_database_path()
        db_status = "Connected" if db_path.exists() else "Ready on first run"
        self.db_status_card = self._create_metric_card("Persistence Engine", db_status, str(db_path.name))
        metrics_layout.addWidget(self.db_status_card)

        layout.addLayout(metrics_layout)

        # 3. Starter Templates Section
        template_header = QLabel("Starter Workflow Templates")
        template_header.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {TEXT_PRIMARY};")
        layout.addWidget(template_header)

        template_grid = QGridLayout()
        template_grid.setSpacing(16)

        for idx, tmpl in enumerate(STARTER_TEMPLATES):
            row = idx // 2
            col = idx % 2
            card = self._create_template_card(tmpl)
            template_grid.addWidget(card, row, col)

        layout.addLayout(template_grid)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _create_metric_card(self, title: str, value: str, subtitle: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("cardFrame")
        l = QVBoxLayout(frame)
        l.setSpacing(4)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {TEXT_MUTED};")
        l.addWidget(t_lbl)

        v_lbl = QLabel(value)
        v_lbl.setObjectName("metricValue")
        v_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {TEXT_PRIMARY};")
        l.addWidget(v_lbl)

        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        l.addWidget(s_lbl)
        return frame

    def _create_template_card(self, tmpl: dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("cardFrame")
        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        title = QLabel(tmpl["title"])
        title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel(tmpl["description"])
        desc.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Tags and action
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(6)

        tags_str = " • ".join(tmpl.get("tags", []))
        tag_lbl = QLabel(tags_str)
        tag_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
        bottom_layout.addWidget(tag_lbl)
        bottom_layout.addStretch()

        use_btn = QPushButton("Use Template →")
        use_btn.setObjectName("secondaryBtn")
        use_btn.clicked.connect(lambda: self.sig_use_template.emit(tmpl["workflow"]))
        bottom_layout.addWidget(use_btn)

        layout.addLayout(bottom_layout)
        return card

    def refresh_metrics(self) -> None:
        """Update metrics for saved workflows and database runs."""
        # 1. Count workflows
        wf_dir = get_workflows_dir()
        count = len(list(wf_dir.glob("*.json"))) if wf_dir.exists() else 0
        v_lbl = self.wf_count_lbl.findChild(QLabel, "metricValue")
        if v_lbl:
            v_lbl.setText(str(count))

        # 2. Count runs
        db_path = get_database_path()
        run_count = 0
        if db_path.exists():
            try:
                store = ExecutionStore.create(db_path)
                runs = store.list_workflow_runs(limit=1000)
                run_count = len(runs)
            except Exception:
                pass
        v_runs = self.runs_count_lbl.findChild(QLabel, "metricValue")
        if v_runs:
            v_runs.setText(str(run_count))

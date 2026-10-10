"""Settings view for Forge Desktop application configuration."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from forge.desktop.paths import (
    get_app_data_dir,
    get_database_path,
    get_logs_dir,
    get_workflows_dir,
)
from forge.desktop.styles import TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY
from forge import __version__


class SettingsView(QWidget):
    """Application settings panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        title = QLabel("Settings")
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        # Data Paths section
        paths_frame = QFrame()
        paths_frame.setObjectName("cardFrame")
        paths_layout = QVBoxLayout(paths_frame)
        paths_layout.setSpacing(10)

        paths_title = QLabel("Data Storage Locations")
        paths_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT_PRIMARY};")
        paths_layout.addWidget(paths_title)

        form = QFormLayout()
        form.setSpacing(8)

        def path_row(label: str, path_str: str) -> None:
            row_layout = QHBoxLayout()
            path_edit = QLineEdit(path_str)
            path_edit.setReadOnly(True)
            row_layout.addWidget(path_edit)
            open_btn = QPushButton("Open Folder")
            open_btn.setObjectName("secondaryBtn")
            open_btn.clicked.connect(lambda _, p=path_str: self._open_folder(p))
            row_layout.addWidget(open_btn)
            form.addRow(label, row_layout)

        path_row("App Data Directory:", str(get_app_data_dir()))
        path_row("Workflows Directory:", str(get_workflows_dir()))
        path_row("Database File:", str(get_database_path()))
        path_row("Logs Directory:", str(get_logs_dir()))

        paths_layout.addLayout(form)
        layout.addWidget(paths_frame)

        # Execution defaults
        exec_frame = QFrame()
        exec_frame.setObjectName("cardFrame")
        exec_layout = QVBoxLayout(exec_frame)

        exec_title = QLabel("Execution Defaults")
        exec_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT_PRIMARY};")
        exec_layout.addWidget(exec_title)

        exec_form = QFormLayout()
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 32)
        self.workers_spin.setValue(4)
        exec_form.addRow("Default Max Workers:", self.workers_spin)
        exec_layout.addLayout(exec_form)
        layout.addWidget(exec_frame)

        # About section
        about_frame = QFrame()
        about_frame.setObjectName("cardFrame")
        about_layout = QVBoxLayout(about_frame)

        about_title = QLabel("About Forge Desktop")
        about_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT_PRIMARY};")
        about_layout.addWidget(about_title)

        version_lbl = QLabel(f"Forge Engine Version: {__version__}")
        version_lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        about_layout.addWidget(version_lbl)

        desc_lbl = QLabel(
            "Forge is a serious Python workflow automation engine with DAG orchestration, "
            "parallel execution, conditional task logic, SQLite persistence, and secret protection."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        about_layout.addWidget(desc_lbl)

        layout.addWidget(about_frame)
        layout.addStretch()

    def _open_folder(self, path: str) -> None:
        import subprocess
        import sys
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as err:
            QMessageBox.warning(self, "Cannot Open Folder", str(err))

"""forge/desktop/__init__.py — Forge Desktop GUI package.

Optional desktop dependency: PySide6.
Import guards prevent CLI and engine users from requiring GUI libraries.
"""

__all__ = ["launch"]


def launch() -> None:
    """Launch the Forge Desktop application.

    Raises:
        ImportError: If PySide6 is not installed.
    """
    try:
        import sys
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise ImportError(
            "Forge Desktop requires PySide6. Install it with:\n"
            "  pip install PySide6"
        ) from exc

    from forge.desktop.main_window import ForgeMainWindow
    from forge.desktop.styles import MAIN_STYLESHEET
    from forge.desktop.paths import ensure_app_directories

    ensure_app_directories()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Forge")
    app.setApplicationDisplayName("Forge Workflow Automation")
    app.setOrganizationName("Forge")
    app.setStyleSheet(MAIN_STYLESHEET)

    window = ForgeMainWindow()
    window.show()

    sys.exit(app.exec())

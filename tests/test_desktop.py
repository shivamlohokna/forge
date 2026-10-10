"""Tests for the Forge Desktop application layer.

These tests validate GUI construction, navigation, template loading,
workflow editing, validation integration, and background execution
using PySide6's offscreen platform.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Safe guard for headless CI environments without PySide6
try:
    if "-platform" not in sys.argv:
        sys.argv.extend(["-platform", "offscreen"])
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    HAS_PYSIDE6 = True
except (ImportError, Exception):
    HAS_PYSIDE6 = False

if not HAS_PYSIDE6:
    import pytest
    pytestmark = pytest.mark.skip(reason="PySide6 is not available in environment")


from forge.desktop.paths import (
    ensure_app_directories,
    get_app_data_dir,
    get_database_path,
    get_workflows_dir,
)
from forge.desktop.styles import MAIN_STYLESHEET
from forge.desktop.templates import get_starter_templates, get_template_by_id
from forge.desktop.main_window import ForgeMainWindow
from forge.desktop.views.home_view import HomeView
from forge.desktop.views.editor_view import TaskEditDialog, WorkflowEditorView
from forge.desktop.views.workflows_view import WorkflowsView
from forge.desktop.views.history_view import HistoryView
from forge.desktop.views.settings_view import SettingsView


class TestDesktopPaths(unittest.TestCase):
    """Verify per-user data directory resolution."""

    def test_app_data_dir_is_absolute(self):
        path = get_app_data_dir()
        self.assertTrue(path.is_absolute())

    def test_workflows_dir_under_app_data(self):
        wf_dir = get_workflows_dir()
        self.assertTrue(str(wf_dir).startswith(str(get_app_data_dir())))

    def test_database_path_under_app_data(self):
        db_path = get_database_path()
        self.assertTrue(str(db_path).startswith(str(get_app_data_dir())))

    def test_ensure_app_directories_creates_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("forge.desktop.paths.get_app_data_dir", return_value=Path(tmp) / "TestForge"):
                with patch("forge.desktop.paths.get_workflows_dir", return_value=Path(tmp) / "TestForge" / "workflows"):
                    with patch("forge.desktop.paths.get_logs_dir", return_value=Path(tmp) / "TestForge" / "logs"):
                        ensure_app_directories()
                        self.assertTrue((Path(tmp) / "TestForge").exists())
                        self.assertTrue((Path(tmp) / "TestForge" / "workflows").exists())


class TestDesktopTemplates(unittest.TestCase):
    """Verify starter workflow templates are well-formed."""

    def test_templates_are_not_empty(self):
        templates = get_starter_templates()
        self.assertGreater(len(templates), 0)

    def test_each_template_has_required_fields(self):
        for tmpl in get_starter_templates():
            self.assertIn("id", tmpl)
            self.assertIn("title", tmpl)
            self.assertIn("workflow", tmpl)
            wf = tmpl["workflow"]
            self.assertIn("name", wf)
            self.assertIn("tasks", wf)
            self.assertIsInstance(wf["tasks"], list)
            self.assertGreater(len(wf["tasks"]), 0)

    def test_get_template_by_id(self):
        tmpl = get_template_by_id("system_health_audit")
        self.assertIsNotNone(tmpl)
        self.assertEqual(tmpl["id"], "system_health_audit")

    def test_get_template_by_id_returns_none_for_unknown(self):
        self.assertIsNone(get_template_by_id("nonexistent_template"))

    def test_templates_are_deep_copies(self):
        t1 = get_starter_templates()
        t2 = get_starter_templates()
        t1[0]["title"] = "MODIFIED"
        self.assertNotEqual(t2[0]["title"], "MODIFIED")


class TestDesktopMainWindow(unittest.TestCase):
    """Test main window construction and navigation."""

    @classmethod
    def setUpClass(cls):
        _app.setStyleSheet(MAIN_STYLESHEET)
        cls.window = ForgeMainWindow()

    def test_window_creates_successfully(self):
        self.assertIsNotNone(self.window)

    def test_window_title_set(self):
        self.assertIn("Forge", self.window.windowTitle())

    def test_navigate_to_all_views(self):
        for key in ("home", "workflows", "editor", "history", "settings"):
            self.window._navigate_to(key)
            # No crash is the test

    def test_create_new_workflow_switches_to_editor(self):
        self.window._on_create_new()
        self.assertEqual(self.window._stack.currentIndex(), 2)  # editor

    def test_use_template_populates_editor(self):
        tmpl = get_starter_templates()[0]
        self.window._on_use_template(tmpl["workflow"])
        editor = self.window.editor_view
        self.assertEqual(editor.wf_name_edit.text(), tmpl["workflow"]["name"])
        self.assertGreater(len(editor.tasks_data), 0)


class TestDesktopEditorView(unittest.TestCase):
    """Test the workflow editor view."""

    def setUp(self):
        self.editor = WorkflowEditorView()

    def test_set_workflow_populates_fields(self):
        wf = {
            "name": "Test WF",
            "description": "Testing",
            "max_workers": 2,
            "tasks": [
                {"name": "t1", "type": "shell", "command": "echo hello", "failure_strategy": "STOP"},
            ],
        }
        self.editor.set_workflow(wf)
        self.assertEqual(self.editor.wf_name_edit.text(), "Test WF")
        self.assertEqual(self.editor.wf_workers_spin.value(), 2)
        self.assertEqual(len(self.editor.tasks_data), 1)

    def test_get_workflow_dict_roundtrip(self):
        wf = {
            "name": "Roundtrip WF",
            "description": "Desc",
            "max_workers": 3,
            "tasks": [
                {"name": "step1", "type": "file", "action": "write", "path": "out.txt",
                 "content": "hello", "failure_strategy": "STOP"},
            ],
        }
        self.editor.set_workflow(wf)
        result = self.editor.get_workflow_dict()
        self.assertEqual(result["name"], "Roundtrip WF")
        self.assertEqual(result["max_workers"], 3)
        self.assertEqual(len(result["tasks"]), 1)

    def test_validate_empty_workflow_returns_false(self):
        self.editor.set_workflow({"name": "Empty", "tasks": []})
        self.assertFalse(self.editor.validate_workflow())

    def test_validate_valid_workflow_returns_true(self):
        wf = {
            "name": "Valid WF",
            "tasks": [
                {"name": "step1", "type": "shell", "command": "echo ok", "failure_strategy": "STOP"},
            ],
        }
        self.editor.set_workflow(wf)
        self.assertTrue(self.editor.validate_workflow())

    def test_save_workflow_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("forge.desktop.views.editor_view.get_workflows_dir", return_value=Path(tmp)):
                wf = {
                    "name": "Save Test",
                    "tasks": [
                        {"name": "s1", "type": "shell", "command": "echo save", "failure_strategy": "STOP"},
                    ],
                }
                self.editor.set_workflow(wf)
                self.assertTrue(self.editor.save_workflow())
                saved = list(Path(tmp).glob("*.json"))
                self.assertEqual(len(saved), 1)
                with open(saved[0]) as f:
                    data = json.load(f)
                self.assertEqual(data["name"], "Save Test")


class TestDesktopHistoryView(unittest.TestCase):
    """Test history view construction."""

    def test_creates_without_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("forge.desktop.views.history_view.get_database_path",
                        return_value=Path(tmp) / "nonexistent.db"):
                view = HistoryView()
                self.assertIsNotNone(view)


class TestDesktopSettingsView(unittest.TestCase):
    """Test settings view construction."""

    def test_creates_successfully(self):
        view = SettingsView()
        self.assertIsNotNone(view)


class TestDesktopWorkflowExecution(unittest.TestCase):
    """Integration test: run a real workflow through the desktop runner."""

    def test_run_file_task_workflow_via_runner(self):
        """Execute a file-write workflow via WorkflowRunnerThread and verify results."""
        from forge.desktop.runner import WorkflowRunnerThread
        from PySide6.QtCore import QEventLoop, QTimer

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            wf = {
                "name": "Desktop Runner Test",
                "tasks": [
                    {
                        "name": "write_test",
                        "type": "file",
                        "action": "write",
                        "path": str(Path(tmp) / "output.txt"),
                        "content": "Forge Desktop works!",
                        "failure_strategy": "STOP",
                    },
                ],
            }

            results = {}

            def on_finished(success, run_id, duration, summary):
                results["success"] = success
                results["run_id"] = run_id
                results["summary"] = summary

            def on_error(err):
                results["error"] = err

            runner = WorkflowRunnerThread(wf, db_path=db_path)
            runner.signals.sig_finished.connect(on_finished)
            runner.signals.sig_error.connect(on_error)
            runner.start()
            runner.wait(10000)  # Wait up to 10 seconds

            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.processEvents()

            self.assertTrue(results.get("success"), f"Workflow failed: {results}")
            self.assertTrue((Path(tmp) / "output.txt").exists())
            content = (Path(tmp) / "output.txt").read_text()
            self.assertEqual(content, "Forge Desktop works!")


if __name__ == "__main__":
    unittest.main()

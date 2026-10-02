"""Tests to verify all canonical beginner and use-case examples run cleanly and cross-platform."""

import shutil
import subprocess
import sys
from pathlib import Path
import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


class TestExamplesExecution:
    def test_quickstart_json_execution(self, tmp_path: Path):
        qs_file = EXAMPLES_DIR / "quickstart.json"
        dest = tmp_path / "quickstart.json"
        shutil.copy(qs_file, dest)

        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "quickstart.json"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "SUCCESS" in proc.stdout
        assert (tmp_path / "data" / "report.json").is_file()

    def test_quickstart_py_execution(self, tmp_path: Path):
        qs_py = EXAMPLES_DIR / "quickstart.py"
        dest = tmp_path / "quickstart.py"
        shutil.copy(qs_py, dest)

        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "quickstart.py"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "SUCCESS" in proc.stdout
        assert (tmp_path / "data" / "report.json").is_file()

    def test_build_test_json_execution(self, tmp_path: Path):
        wf = EXAMPLES_DIR / "declarative" / "build_test.json"
        dest = tmp_path / "build_test.json"
        shutil.copy(wf, dest)

        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "build_test.json"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "SUCCESS" in proc.stdout
        assert (tmp_path / "build" / "artifact.txt").is_file()

    def test_file_pipeline_json_execution(self, tmp_path: Path):
        wf = EXAMPLES_DIR / "declarative" / "file_pipeline.json"
        dest = tmp_path / "file_pipeline.json"
        shutil.copy(wf, dest)

        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "file_pipeline.json"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "SUCCESS" in proc.stdout
        assert (tmp_path / "data" / "processed.txt").is_file()

    def test_backup_workflow_json_execution(self, tmp_path: Path):
        wf = EXAMPLES_DIR / "declarative" / "backup_workflow.json"
        dest = tmp_path / "backup_workflow.json"
        shutil.copy(wf, dest)

        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "backup_workflow.json"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "SUCCESS" in proc.stdout
        assert (tmp_path / "storage" / "backups" / "db_dump_backup.json").is_file()

    def test_ml_pipeline_json_execution(self, tmp_path: Path):
        wf = EXAMPLES_DIR / "declarative" / "ml_pipeline.json"
        dest = tmp_path / "ml_pipeline.json"
        shutil.copy(wf, dest)

        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "ml_pipeline.json"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "SUCCESS" in proc.stdout
        assert (tmp_path / "ml" / "model_metrics.json").is_file()

"""Tests for new CLI productization commands (init, doctor, tasks, examples) and error formatting."""

import json
import subprocess
import sys
from pathlib import Path
import pytest

from forge.cli import (
    doctor_command,
    examples_command,
    init_command,
    tasks_command,
)
from forge.cli.main import main


class TestInitCommand:
    def test_init_creates_files(self, tmp_path: Path, capsys):
        target = tmp_path / "my_project"
        code = init_command(target)
        assert code == 0
        assert (target / "forge.toml").is_file()
        assert (target / "workflow.json").is_file()
        captured = capsys.readouterr()
        assert "Initialized project in" in captured.out
        assert "+ Created forge.toml" in captured.out
        assert "+ Created workflow.json" in captured.out

    def test_init_skips_existing(self, tmp_path: Path, capsys):
        target = tmp_path / "my_project"
        init_command(target)
        capsys.readouterr()

        # Second init call
        code = init_command(target)
        assert code == 0
        captured = capsys.readouterr()
        assert "~ Skipped forge.toml (already exists)" in captured.out
        assert "~ Skipped workflow.json (already exists)" in captured.out

    def test_init_cli_dispatch(self, tmp_path: Path, capsys):
        target = tmp_path / "cli_init"
        code = main(["init", str(target)])
        assert code == 0
        assert (target / "forge.toml").is_file()
        assert (target / "workflow.json").is_file()


class TestDoctorCommand:
    def test_doctor_table_output(self, capsys):
        code = doctor_command()
        assert code == 0
        captured = capsys.readouterr()
        assert "Forge Health Diagnostics" in captured.out
        assert "Python Environment" in captured.out
        assert "Forge Package" in captured.out
        assert "Task Registry & Plugins" in captured.out
        assert "All diagnostics PASSED" in captured.out

    def test_doctor_json_output(self, capsys):
        code = doctor_command(output_format="json")
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["healthy"] is True
        assert len(data["checks"]) >= 4

    def test_doctor_cli_dispatch(self, capsys):
        code = main(["doctor", "--json"])
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["healthy"] is True


class TestTasksCommand:
    def test_tasks_table_output(self, capsys):
        code = tasks_command()
        assert code == 0
        captured = capsys.readouterr()
        assert "Available Task Types:" in captured.out
        assert "function" in captured.out
        assert "file" in captured.out
        assert "shell" in captured.out
        assert "http" in captured.out

    def test_tasks_json_output(self, capsys):
        code = tasks_command(output_format="json")
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        types = [t["type"] for t in data]
        assert "function" in types
        assert "file" in types
        assert "shell" in types
        assert "http" in types

    def test_tasks_cli_dispatch(self, capsys):
        code = main(["tasks", "--json"])
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) >= 4


class TestExamplesCommand:
    def test_examples_table_output(self, capsys):
        code = examples_command()
        assert code == 0
        captured = capsys.readouterr()
        assert "Available Runnable Workflow Examples:" in captured.out
        assert "quickstart" in captured.out
        assert "build_test" in captured.out

    def test_examples_json_output(self, capsys):
        code = examples_command(output_format="json")
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        names = [e["name"] for e in data]
        assert "quickstart" in names
        assert "build_test" in names

    def test_examples_copy_success(self, tmp_path: Path, capsys):
        target_file = tmp_path / "copied_qs.json"
        code = examples_command(copy_name="quickstart", target_path=target_file)
        assert code == 0
        assert target_file.is_file()
        captured = capsys.readouterr()
        assert "Copied example 'quickstart'" in captured.out

    def test_examples_copy_unknown(self, capsys):
        code = examples_command(copy_name="nonexistent_example")
        assert code == 2
        captured = capsys.readouterr()
        assert "Unknown example" in captured.err

    def test_examples_cli_dispatch(self, tmp_path: Path, capsys):
        dest = tmp_path / "quickstart.json"
        code = main(["examples", "--copy", "quickstart", "--target", str(dest)])
        assert code == 0
        assert dest.is_file()


class TestBeginnerJourneyIntegration:
    def test_full_beginner_cli_journey(self, tmp_path: Path):
        # 1. Run init in clean directory
        proj_dir = tmp_path / "beginner_proj"
        proc_init = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "init", str(proj_dir)],
            capture_output=True,
            text=True,
        )
        assert proc_init.returncode == 0
        assert (proj_dir / "workflow.json").is_file()

        # 2. Run doctor
        proc_doc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "doctor", "--json"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert proc_doc.returncode == 0
        doc_json = json.loads(proc_doc.stdout)
        assert doc_json["healthy"] is True

        # 3. Validate initial workflow
        proc_val = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "validate", "workflow.json"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert proc_val.returncode == 0
        assert "is valid" in proc_val.stdout

        # 4. Run workflow
        proc_run = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "workflow.json"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert proc_run.returncode == 0
        assert "SUCCESS" in proc_run.stdout
        assert (proj_dir / "data" / "report.json").is_file()

        # 5. History check
        proc_hist = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "history"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert proc_hist.returncode == 0
        assert "QuickstartPipeline" in proc_hist.stdout
        assert "SUCCESS" in proc_hist.stdout

        # Extract run ID from history JSON
        proc_hist_json = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "history", "--json"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        runs = json.loads(proc_hist_json.stdout)
        assert len(runs) >= 1
        run_id = runs[0]["run_id"]

        # 6. Inspect check
        proc_insp = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "inspect", run_id],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert proc_insp.returncode == 0
        assert f"Workflow Run #{run_id}" in proc_insp.stdout

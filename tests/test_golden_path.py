"""Golden Path & Release Reliability Integration Tests.

Simulates the complete clean-user onboarding journey and failure recovery
scenarios end-to-end via CLI subprocess execution.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
import pytest


class TestGoldenPathIntegration:
    """Golden path user journey tests."""

    def test_complete_golden_path_journey(self, tmp_path: Path):
        """Simulate clean user journey: init -> validate -> run -> history -> inspect -> doctor."""
        proj_dir = tmp_path / "golden_project"
        proj_dir.mkdir(parents=True, exist_ok=True)

        # 1. forge init
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "init"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert (proj_dir / "forge.toml").is_file()
        assert (proj_dir / "workflow.json").is_file()

        # 2. forge validate workflow.json
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "validate", "workflow.json"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "is valid" in res.stdout

        # 3. forge run workflow.json
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "workflow.json"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "SUCCESS" in res.stdout
        assert (proj_dir / "data" / "report.json").is_file()

        # 4. forge history
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "history"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "QuickstartPipeline" in res.stdout

        # 5. forge history --json
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "history", "--json"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        runs = json.loads(res.stdout)
        assert len(runs) >= 1
        run_id = runs[0]["run_id"]

        # 6. forge inspect <run_id>
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "inspect", run_id],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert f"Workflow Run #{run_id}" in res.stdout

        # 7. forge doctor
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "doctor"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "All diagnostics PASSED" in res.stdout


class TestFailureJourneysAndExitCodes:
    """Failure journeys and exit code verification tests."""

    def test_missing_workflow_file(self, tmp_path: Path):
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "nonexistent.json"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 2
        assert "Error" in res.stderr
        assert "Traceback" not in res.stderr

    def test_invalid_json_workflow_file(self, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", str(bad_file)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 3
        assert "Validation error" in res.stderr or "Error" in res.stderr
        assert "Traceback" not in res.stderr


    def test_cyclic_dependency_validation(self, tmp_path: Path):
        cyclic_file = tmp_path / "cyclic.json"
        cyclic_file.write_text(
            json.dumps({
                "name": "CyclicWF",
                "tasks": [
                    {"id": "t1", "type": "file", "depends_on": ["t2"], "params": {"operation": "write", "path": "a.txt", "content": "a"}},
                    {"id": "t2", "type": "file", "depends_on": ["t1"], "params": {"operation": "write", "path": "b.txt", "content": "b"}},
                ],
            }),
            encoding="utf-8",
        )
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "validate", str(cyclic_file)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 3
        assert "Validation error" in res.stderr

    def test_failing_task_workflow(self, tmp_path: Path):
        fail_file = tmp_path / "fail.json"
        fail_file.write_text(
            json.dumps({
                "name": "FailWF",
                "tasks": [
                    {
                        "id": "broken_shell",
                        "type": "shell",
                        "params": {"command": 'python -c "import sys; sys.exit(1)"'},
                    }
                ],
            }),
            encoding="utf-8",
        )
        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", str(fail_file)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 1
        assert "FAILED" in res.stdout

        # History should record the failure
        hist_res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "history", "--json"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert hist_res.returncode == 0
        runs = json.loads(hist_res.stdout)
        assert len(runs) >= 1
        assert runs[0]["status"] == "FAILED"


class TestWindowsPathsWithSpaces:
    """Windows-specific path safety and spaces handling tests."""

    def test_run_in_directory_with_spaces(self, tmp_path: Path):
        space_dir = tmp_path / "Space Path Project Test"
        space_dir.mkdir(parents=True, exist_ok=True)

        res = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "init"],
            cwd=str(space_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert (space_dir / "workflow.json").is_file()

        res_run = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", "workflow.json"],
            cwd=str(space_dir),
            capture_output=True,
            text=True,
        )
        assert res_run.returncode == 0
        assert "SUCCESS" in res_run.stdout
        assert (space_dir / "data" / "report.json").is_file()

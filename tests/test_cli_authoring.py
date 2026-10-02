"""Tests for Phase 4 Workflow Authoring & Real-World Experience features.

Tests cover:
- forge plan (dry-run preflight inspection, zero side effects, exit codes, JSON output)
- forge tasks (rich task schemas, key parameters, minimal examples, JSON output)
- forge examples (recipe catalog, --show recipe inspection, --copy, JSON output)
- Authoring error diagnostics (WHAT, WHY, NEXT STEP)
- Golden User Journeys A, B, and C
"""

import json
from pathlib import Path
from typing import Any

import pytest
from _pytest.capture import CaptureFixture

from forge.cli.main import main


def run_cli(args: list[str], capsys: CaptureFixture[str]) -> tuple[int, str, str]:
    """Helper to run CLI main() and return (exit_code, stdout, stderr)."""
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --------------------------------------------------------------------------- #
# 1. forge plan Tests
# --------------------------------------------------------------------------- #

class TestForgePlanCommand:
    """Test suite for 'forge plan' workflow preflight preview command."""

    def test_plan_quickstart_table_output(self, capsys: CaptureFixture[str]) -> None:
        """forge plan shows execution batches, task dependencies, and safety summary."""
        code, out, err = run_cli(["plan", "examples/quickstart.json"], capsys)
        assert code == 0
        assert "Workflow Plan: QuickstartPipeline" in out
        assert "Execution Plan (3 tasks across 3 batches)" in out
        assert "Batch 1:" in out
        assert "1. prepare_data" in out
        assert "Batch 2:" in out
        assert "2. verify_data" in out
        assert "Batch 3:" in out
        assert "3. save_report" in out
        assert "Preflight Safety Summary:" in out
        assert "[OK] Execution DAG is valid" in out
        assert "[OK] Dry run complete - no side effects created" in out

    def test_plan_json_output(self, capsys: CaptureFixture[str]) -> None:
        """forge plan --json returns structured machine-readable execution plan."""
        code, out, err = run_cli(["plan", "examples/quickstart.json", "--json"], capsys)
        assert code == 0
        data = json.loads(out)
        assert data["workflow_name"] == "QuickstartPipeline"
        assert data["total_tasks"] == 3
        assert data["total_batches"] == 3
        assert data["valid"] is True
        assert len(data["batches"]) == 3
        assert data["batches"][0]["tasks"][0]["task_id"] == "prepare_data"

    def test_plan_zero_side_effects(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """forge plan must NOT create files, modified state, or persistence DB rows."""
        wf_file = tmp_path / "plan_test.json"
        target_file = tmp_path / "should_not_exist.txt"
        wf_data = {
            "name": "SideEffectCheck",
            "tasks": [
                {
                    "id": "write_file",
                    "type": "file",
                    "params": {
                        "operation": "write",
                        "path": str(target_file),
                        "content": "Secret payload"
                    }
                }
            ]
        }
        wf_file.write_text(json.dumps(wf_data), encoding="utf-8")

        code, out, err = run_cli(["plan", str(wf_file)], capsys)
        assert code == 0
        assert not target_file.exists(), "forge plan must not execute tasks or create files"

    def test_plan_missing_file_exit_code_2(self, capsys: CaptureFixture[str]) -> None:
        """forge plan with missing file returns exit code 2."""
        code, out, err = run_cli(["plan", "non_existent_file.json"], capsys)
        assert code == 2
        assert "Error loading workflow" in err or "not found" in err

    def test_plan_circular_dependency_exit_code_3(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """forge plan with circular dependency returns exit code 3."""
        wf_file = tmp_path / "cycle.json"
        wf_data = {
            "name": "CyclePipeline",
            "tasks": [
                {"id": "task_a", "type": "file", "depends_on": ["task_b"], "params": {"operation": "read", "path": "a"}},
                {"id": "task_b", "type": "file", "depends_on": ["task_a"], "params": {"operation": "read", "path": "b"}}
            ]
        }
        wf_file.write_text(json.dumps(wf_data), encoding="utf-8")

        code, out, err = run_cli(["plan", str(wf_file)], capsys)
        assert code == 3
        assert "Validation error" in err


# --------------------------------------------------------------------------- #
# 2. forge tasks Tests
# --------------------------------------------------------------------------- #

class TestForgeTasksCommand:
    """Test suite for 'forge tasks' schema and example discovery command."""

    def test_tasks_table_output(self, capsys: CaptureFixture[str]) -> None:
        """forge tasks shows built-in task types, operations, key params, and minimal examples."""
        code, out, err = run_cli(["tasks"], capsys)
        assert code == 0
        assert "Available Task Types:" in out
        assert "Task Type: file" in out
        assert "Operations: read, write, copy, move, delete" in out
        assert "Task Type: shell" in out
        assert "Task Type: http" in out
        assert "Minimal Example:" in out

    def test_tasks_json_output(self, capsys: CaptureFixture[str]) -> None:
        """forge tasks --json returns structured list of task objects."""
        code, out, err = run_cli(["tasks", "--json"], capsys)
        assert code == 0
        tasks_list = json.loads(out)
        assert isinstance(tasks_list, list)
        types = [t["type"] for t in tasks_list]
        assert "file" in types
        assert "shell" in types
        assert "http" in types
        file_task = next(t for t in tasks_list if t["type"] == "file")
        assert "read" in file_task["operations"]
        assert "example" in file_task


# --------------------------------------------------------------------------- #
# 3. forge examples Tests
# --------------------------------------------------------------------------- #

class TestForgeExamplesCommand:
    """Test suite for 'forge examples' recipe catalog and show/copy functionality."""

    def test_examples_catalog_listing(self, capsys: CaptureFixture[str]) -> None:
        """forge examples lists categorized runnable recipes."""
        code, out, err = run_cli(["examples"], capsys)
        assert code == 0
        assert "Available Runnable Workflow Examples:" in out
        assert "[Getting Started]" in out
        assert "quickstart" in out
        assert "[Developer Automation]" in out
        assert "build_test" in out

    def test_examples_show_recipe_card(self, capsys: CaptureFixture[str]) -> None:
        """forge examples --show quickstart prints structured recipe details."""
        code, out, err = run_cli(["examples", "--show", "quickstart"], capsys)
        assert code == 0
        assert "Forge Recipe: quickstart" in out
        assert "PROBLEM:" in out
        assert "WHAT FORGE DOES:" in out
        assert "WHAT YOU NEED:" in out
        assert "RUN IT:" in out
        assert "WHAT YOU WILL SEE:" in out
        assert "HOW TO CUSTOMIZE IT:" in out
        assert "WHAT CAN GO WRONG:" in out

    def test_examples_copy_workflow(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """forge examples --copy quickstart copies recipe into target path."""
        target = tmp_path / "my_quickstart.json"
        code, out, err = run_cli(["examples", "--copy", "quickstart", "--target", str(target)], capsys)
        assert code == 0
        assert target.is_file()
        assert "QuickstartPipeline" in target.read_text(encoding="utf-8")

    def test_examples_json_output(self, capsys: CaptureFixture[str]) -> None:
        """forge examples --json returns machine-readable recipe catalog."""
        code, out, err = run_cli(["examples", "--json"], capsys)
        assert code == 0
        catalog = json.loads(out)
        assert isinstance(catalog, list)
        names = [item["name"] for item in catalog]
        assert "quickstart" in names
        assert "build_test" in names


# --------------------------------------------------------------------------- #
# 4. Authoring Error Experience Tests
# --------------------------------------------------------------------------- #

class TestAuthoringDiagnostics:
    """Verify human-friendly error messages for common authoring mistakes."""

    def test_unknown_task_type_diagnostic(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """Unknown task type error provides 'Next step' guidance to run forge tasks."""
        wf_file = tmp_path / "typo_task.json"
        wf_data = {
            "name": "TypoPipeline",
            "tasks": [
                {"id": "step1", "type": "proces", "params": {}}
            ]
        }
        wf_file.write_text(json.dumps(wf_data), encoding="utf-8")

        code, out, err = run_cli(["validate", str(wf_file)], capsys)
        assert code == 3
        assert "unknown task type 'proces'" in err
        assert "Next step: Run 'forge tasks'" in err


# --------------------------------------------------------------------------- #
# 5. Golden User Journeys A, B, C
# --------------------------------------------------------------------------- #

class TestGoldenUserJourneys:
    """End-to-end integration tests for Golden User Journeys."""

    def test_journey_a_first_workflow(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """Journey A: forge init -> validate -> plan -> run -> history -> inspect."""
        # 1. init
        code_init, out_init, err_init = run_cli(["init", str(tmp_path)], capsys)
        assert code_init == 0
        assert "Initialized project" in out_init
        wf_file = tmp_path / "workflow.json"
        db_file = tmp_path / ".forge" / "execution.db"

        # 2. validate
        code_val, out_val, err_val = run_cli(["validate", str(wf_file)], capsys)
        assert code_val == 0
        assert "valid" in out_val

        # 3. plan
        code_plan, out_plan, err_plan = run_cli(["plan", str(wf_file)], capsys)
        assert code_plan == 0
        assert "Execution Plan" in out_plan

        # 4. run
        code_run, out_run, err_run = run_cli(["run", str(wf_file), "--db", str(db_file)], capsys)
        assert code_run == 0
        assert "SUCCESS" in out_run

        # 5. history
        code_hist, out_hist, err_hist = run_cli(["history", "--db", str(db_file)], capsys)
        assert code_hist == 0
        assert "QuickstartPipeline" in out_hist

        # 6. inspect
        code_insp, out_insp, err_insp = run_cli(["inspect", "QuickstartPipeline", "--db", str(db_file)], capsys)
        assert code_insp == 0
        assert "Workflow Run #" in out_insp
        assert "QuickstartPipeline" in out_insp

    def test_journey_b_adapt_example(self, tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        """Journey B: forge examples -> copy recipe -> modify workflow -> plan -> run."""
        monkeypatch.chdir(tmp_path)
        # 1. copy recipe
        recipe_file = tmp_path / "copied_build.json"
        code_copy, out_copy, _ = run_cli(["examples", "--copy", "build_test", "--target", str(recipe_file)], capsys)
        assert code_copy == 0
        assert recipe_file.is_file()

        # 2. modify workflow
        data = json.loads(recipe_file.read_text(encoding="utf-8"))
        data["name"] = "CustomizedBuildPipeline"
        recipe_file.write_text(json.dumps(data), encoding="utf-8")

        # 3. plan
        code_plan, out_plan, _ = run_cli(["plan", str(recipe_file)], capsys)
        assert code_plan == 0
        assert "CustomizedBuildPipeline" in out_plan

        # 4. run
        db_file = tmp_path / "demo.db"
        code_run, out_run, _ = run_cli(["run", str(recipe_file), "--db", str(db_file)], capsys)
        assert code_run == 0
        assert "SUCCESS" in out_run

    def test_journey_c_authoring_failure_diagnostic(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """Journey C: invalid workflow -> validate -> human-friendly diagnostic message."""
        invalid_wf = tmp_path / "broken.json"
        invalid_wf.write_text(json.dumps({
            "name": "BrokenPipeline",
            "tasks": [
                {"id": "t1", "type": "file", "depends_on": ["missing_task"], "params": {"operation": "read", "path": "p"}}
            ]
        }), encoding="utf-8")

        code_val, out_val, err_val = run_cli(["validate", str(invalid_wf)], capsys)
        assert code_val == 3
        assert "unknown task id 'missing_task'" in err_val

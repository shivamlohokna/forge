import json
import subprocess
import sys
from pathlib import Path
import pytest

from forge import FunctionTask, Workflow
from forge.cli import (
    history_command,
    inspect_command,
    load_workflow,
    run_command,
    validate_command,
)
from forge.cli.main import build_parser, main
from forge.exceptions import LoadError
from forge.persistence import ExecutionStore


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_workflow_file(tmp_path: Path) -> Path:
    """Creates a temporary workflow file with get_workflow() contract."""
    file_path = tmp_path / "wf_valid.py"
    file_path.write_text(
        """from forge import FunctionTask, Workflow

def step_one(ctx):
    return "hello"

def step_two(ctx):
    val = ctx.get_upstream_result("step_one")
    return f"{val} world"

def get_workflow():
    t1 = FunctionTask("step_one", fn=step_one)
    t2 = FunctionTask("step_two", fn=step_two)
    t1 >> t2
    wf = Workflow(name="ValidWorkflow")
    wf.add_task(t2)
    return wf
""",
        encoding="utf-8",
    )
    return file_path


@pytest.fixture
def variable_workflow_file(tmp_path: Path) -> Path:
    """Creates a temporary workflow file defining a module-level 'workflow' variable."""
    file_path = tmp_path / "wf_variable.py"
    file_path.write_text(
        """from forge import FunctionTask, Workflow

def step_one(ctx):
    return 42

t = FunctionTask("step_one", fn=step_one)
workflow = Workflow(name="VariableWorkflow")
workflow.add_task(t)
""",
        encoding="utf-8",
    )
    return file_path


@pytest.fixture
def failing_workflow_file(tmp_path: Path) -> Path:
    """Creates a workflow file with a task that fails."""
    file_path = tmp_path / "wf_failing.py"
    file_path.write_text(
        """from forge import FunctionTask, Workflow

def broken_step(ctx):
    raise ValueError("Intentional task failure")

def get_workflow():
    t = FunctionTask("broken_step", fn=broken_step)
    wf = Workflow(name="FailingWorkflow")
    wf.add_task(t)
    return wf
""",
        encoding="utf-8",
    )
    return file_path


@pytest.fixture
def cyclic_workflow_file(tmp_path: Path) -> Path:
    """Creates a workflow file containing a circular dependency."""
    file_path = tmp_path / "wf_cyclic.py"
    file_path.write_text(
        """from forge import FunctionTask, Workflow

def dummy(ctx):
    return 1

def get_workflow():
    t1 = FunctionTask("task_a", fn=dummy)
    t2 = FunctionTask("task_b", fn=dummy)
    t1 >> t2 >> t1
    wf = Workflow(name="CyclicWorkflow")
    wf.add_tasks(t1, t2)
    return wf
""",
        encoding="utf-8",
    )
    return file_path


@pytest.fixture
def missing_dep_workflow_file(tmp_path: Path) -> Path:
    """Creates a workflow file containing a missing dependency."""
    file_path = tmp_path / "wf_missing_dep.py"
    file_path.write_text(
        """from forge import FunctionTask, Workflow

def dummy(ctx):
    return 1

def get_workflow():
    outside = FunctionTask("outside_task", fn=dummy)
    inside = FunctionTask("inside_task", fn=dummy)
    wf = Workflow(name="MissingDepWorkflow")
    wf.add_task(inside)
    # Manually attach dependency outside the workflow
    inside.dependencies.add(outside)
    return wf

""",
        encoding="utf-8",
    )
    return file_path


# ── Loader Tests ─────────────────────────────────────────────────────────────

class TestWorkflowLoader:
    def test_load_workflow_via_get_workflow(self, valid_workflow_file: Path):
        wf = load_workflow(valid_workflow_file)
        assert isinstance(wf, Workflow)
        assert wf.name == "ValidWorkflow"
        assert len(wf.tasks) == 2

    def test_load_workflow_via_variable(self, variable_workflow_file: Path):
        wf = load_workflow(variable_workflow_file)
        assert isinstance(wf, Workflow)
        assert wf.name == "VariableWorkflow"
        assert len(wf.tasks) == 1

    def test_loader_returns_fresh_instance(self, valid_workflow_file: Path):
        wf1 = load_workflow(valid_workflow_file)
        wf2 = load_workflow(valid_workflow_file)
        assert wf1 is not wf2
        assert wf1.workflow_id != wf2.workflow_id

    def test_load_nonexistent_file(self, tmp_path: Path):
        fake_path = tmp_path / "nonexistent.py"
        with pytest.raises(LoadError, match="not found"):
            load_workflow(fake_path)

    def test_load_non_python_extension(self, tmp_path: Path):
        txt_file = tmp_path / "workflow.txt"
        txt_file.write_text("dummy", encoding="utf-8")
        with pytest.raises(LoadError, match=r"Unsupported workflow file format"):
            load_workflow(txt_file)


    def test_load_syntax_error_file(self, tmp_path: Path):
        bad_file = tmp_path / "syntax_error.py"
        bad_file.write_text("def def invalid syntax :", encoding="utf-8")
        with pytest.raises(LoadError, match="Error executing workflow file"):
            load_workflow(bad_file)

    def test_load_file_missing_entrypoint(self, tmp_path: Path):
        plain_file = tmp_path / "no_workflow.py"
        plain_file.write_text("x = 10\ny = 20\n", encoding="utf-8")
        with pytest.raises(LoadError, match="must define either a 'get_workflow\\(\\)' function"):
            load_workflow(plain_file)

    def test_load_get_workflow_returns_wrong_type(self, tmp_path: Path):
        bad_file = tmp_path / "bad_return.py"
        bad_file.write_text("def get_workflow(): return 'not_a_workflow'\n", encoding="utf-8")
        with pytest.raises(LoadError, match="must return a Workflow instance"):
            load_workflow(bad_file)

    def test_load_get_workflow_not_callable(self, tmp_path: Path):
        bad_file = tmp_path / "not_callable.py"
        bad_file.write_text("get_workflow = 12345\n", encoding="utf-8")
        with pytest.raises(LoadError, match="is not callable"):
            load_workflow(bad_file)

    def test_load_get_workflow_raises_exception(self, tmp_path: Path):
        raising_file = tmp_path / "raising_wf.py"
        raising_file.write_text(
            "def get_workflow(): raise RuntimeError('Config failed')\n",
            encoding="utf-8",
        )
        with pytest.raises(LoadError, match="Error calling 'get_workflow\\(\\)'"):
            load_workflow(raising_file)

    def test_load_variable_wrong_type(self, tmp_path: Path):
        bad_file = tmp_path / "bad_var.py"
        bad_file.write_text("workflow = {'not': 'a_workflow'}\n", encoding="utf-8")
        with pytest.raises(LoadError, match="must be a Workflow instance"):
            load_workflow(bad_file)


# ── Validate Command Tests ───────────────────────────────────────────────────

class TestValidateCommand:
    def test_validate_valid_workflow(self, valid_workflow_file: Path, capsys):
        code = validate_command(valid_workflow_file)
        assert code == 0
        captured = capsys.readouterr()
        assert "Workflow 'ValidWorkflow' is valid (2 tasks)." in captured.out

    def test_validate_cyclic_workflow(self, cyclic_workflow_file: Path, capsys):
        code = validate_command(cyclic_workflow_file)
        assert code == 3
        captured = capsys.readouterr()
        assert "Validation error" in captured.err
        assert "Circular dependency detected" in captured.err

    def test_validate_missing_dependency(self, missing_dep_workflow_file: Path, capsys):
        code = validate_command(missing_dep_workflow_file)
        assert code == 3
        captured = capsys.readouterr()
        assert "Validation error" in captured.err
        assert "depends on task" in captured.err

    def test_validate_nonexistent_file(self, tmp_path: Path, capsys):
        code = validate_command(tmp_path / "does_not_exist.py")
        assert code == 2
        captured = capsys.readouterr()
        assert "Error loading workflow" in captured.err


# ── Run Command Tests ────────────────────────────────────────────────────────

class TestRunCommand:
    def test_run_successful_workflow(self, valid_workflow_file: Path, capsys):
        code = run_command(valid_workflow_file)
        assert code == 0
        captured = capsys.readouterr()
        assert "=== Workflow Execution Summary: ValidWorkflow ===" in captured.out
        assert "Status:    SUCCESS" in captured.out
        assert "2 succeeded, 0 failed" in captured.out

    def test_run_failing_workflow(self, failing_workflow_file: Path, capsys):
        code = run_command(failing_workflow_file)
        assert code == 1
        captured = capsys.readouterr()
        assert "Status:    FAILED" in captured.out
        assert "1 failed" in captured.out

    def test_run_quiet_flag(self, valid_workflow_file: Path, capsys):
        code = run_command(valid_workflow_file, quiet=True)
        assert code == 0
        captured = capsys.readouterr()
        assert "Workflow Execution Summary" not in captured.out
        assert "[Forge] Starting workflow" not in captured.out

    def test_run_with_persistence_store(self, valid_workflow_file: Path, tmp_path: Path):
        db_path = tmp_path / "forge_cli_test.db"
        code = run_command(valid_workflow_file, db_path=db_path, quiet=True)
        assert code == 0
        assert db_path.exists()

        # Check that execution was durably persisted
        store = ExecutionStore.create(db_path)
        runs = store.list_workflow_runs()
        assert len(runs) == 1
        assert runs[0].workflow_name == "ValidWorkflow"
        assert runs[0].status == "SUCCESS"
        assert runs[0].total_tasks == 2
        store.close()

    def test_run_with_workers(self, valid_workflow_file: Path, capsys):
        code = run_command(valid_workflow_file, workers=2, quiet=False)
        assert code == 0
        captured = capsys.readouterr()
        assert "Status:    SUCCESS" in captured.out

    def test_run_nonexistent_file(self, tmp_path: Path, capsys):
        code = run_command(tmp_path / "missing.py")
        assert code == 2
        captured = capsys.readouterr()
        assert "Error loading workflow" in captured.err


# ── History Command Tests ───────────────────────────────────────────────────

class TestHistoryCommand:
    def test_history_nonexistent_db(self, tmp_path: Path, capsys):
        missing_db = tmp_path / "ghost.db"
        code = history_command(db_path=missing_db)
        assert code == 2
        captured = capsys.readouterr()
        assert "Database file" in captured.err and "not found" in captured.err

    def test_history_empty_db(self, tmp_path: Path, capsys):
        empty_db = tmp_path / "empty.db"
        store = ExecutionStore.create(empty_db)
        store.close()

        code = history_command(db_path=empty_db)
        assert code == 0
        captured = capsys.readouterr()
        assert "No execution history found" in captured.out

    def test_history_populated_display(self, valid_workflow_file: Path, tmp_path: Path, capsys):
        db_path = tmp_path / "hist.db"
        run_command(valid_workflow_file, db_path=db_path, quiet=True)

        code = history_command(db_path=db_path)
        assert code == 0
        captured = capsys.readouterr()
        assert "Forge Execution History" in captured.out
        assert "RUN ID" in captured.out
        assert "WORKFLOW ID" in captured.out
        assert "ValidWorkflow" in captured.out
        assert "SUCCESS" in captured.out

    def test_history_filter_workflow(self, valid_workflow_file: Path, failing_workflow_file: Path, tmp_path: Path, capsys):
        db_path = tmp_path / "hist_filter.db"
        run_command(valid_workflow_file, db_path=db_path, quiet=True)
        run_command(failing_workflow_file, db_path=db_path, quiet=True)

        # Filter by workflow name
        code = history_command(db_path=db_path, workflow="ValidWorkflow")
        assert code == 0
        captured = capsys.readouterr()
        assert "ValidWorkflow" in captured.out
        assert "FailingWorkflow" not in captured.out

    def test_history_filter_status(self, valid_workflow_file: Path, failing_workflow_file: Path, tmp_path: Path, capsys):
        db_path = tmp_path / "hist_status.db"
        run_command(valid_workflow_file, db_path=db_path, quiet=True)
        run_command(failing_workflow_file, db_path=db_path, quiet=True)

        # Filter by status FAILED
        code = history_command(db_path=db_path, status="FAILED")
        assert code == 0
        captured = capsys.readouterr()
        assert "FailingWorkflow" in captured.out
        assert "ValidWorkflow" not in captured.out

    def test_history_limit(self, valid_workflow_file: Path, tmp_path: Path, capsys):
        db_path = tmp_path / "hist_limit.db"
        for _ in range(5):
            run_command(valid_workflow_file, db_path=db_path, quiet=True)

        code = history_command(db_path=db_path, limit=2)
        assert code == 0
        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().splitlines() if "ValidWorkflow" in line]
        assert len(lines) == 2


# ── Inspect Command Tests ───────────────────────────────────────────────────

class TestInspectCommand:
    def test_inspect_nonexistent_db(self, tmp_path: Path, capsys):
        missing_db = tmp_path / "ghost.db"
        code = inspect_command(run_id="run_123", db_path=missing_db)
        assert code == 2
        captured = capsys.readouterr()
        assert "Database file" in captured.err and "not found" in captured.err

    def test_inspect_unknown_run_id(self, tmp_path: Path, capsys):
        db_path = tmp_path / "test.db"
        store = ExecutionStore.create(db_path)
        store.close()

        code = inspect_command(run_id="run_nonexistent", db_path=db_path)
        assert code == 2
        captured = capsys.readouterr()
        assert "run_nonexistent" in captured.err and "not found" in captured.err

    def test_inspect_successful_run(self, valid_workflow_file: Path, tmp_path: Path, capsys):
        db_path = tmp_path / "inspect.db"
        run_command(valid_workflow_file, db_path=db_path, quiet=True)

        store = ExecutionStore.create(db_path)
        runs = store.list_workflow_runs()
        run_id = runs[0].run_id
        store.close()

        code = inspect_command(run_id=run_id, db_path=db_path)
        assert code == 0
        captured = capsys.readouterr()
        assert f"Workflow Run #{run_id}" in captured.out
        assert "ValidWorkflow" in captured.out
        assert "SUCCESS" in captured.out
        assert "step_one" in captured.out
        assert "step_two" in captured.out

    def test_inspect_failing_and_blocked_run(self, tmp_path: Path, capsys):
        file_path = tmp_path / "wf_blocked.py"
        file_path.write_text(
            """from forge import FunctionTask, Workflow

def boom(ctx):
    raise ValueError("Explosion in step A")

def downstream(ctx):
    return "ok"

def get_workflow():
    t1 = FunctionTask("step_a", fn=boom)
    t2 = FunctionTask("step_b", fn=downstream)
    t1 >> t2
    wf = Workflow(name="CascadeWorkflow")
    wf.add_tasks(t1, t2)
    return wf
""",
            encoding="utf-8",
        )
        db_path = tmp_path / "cascade.db"
        run_command(file_path, db_path=db_path, quiet=True)

        store = ExecutionStore.create(db_path)
        runs = store.list_workflow_runs()
        run_id = runs[0].run_id
        store.close()

        code = inspect_command(run_id=run_id, db_path=db_path)
        assert code == 0
        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "Status:" in captured.out
        assert "step_a" in captured.out
        assert "Explosion in step A" in captured.out
        assert "step_b" in captured.out
        assert "BLOCKED" in captured.out

    def test_inspect_with_task_retry_attempts(self, tmp_path: Path, capsys):
        file_path = tmp_path / "wf_retry.py"
        file_path.write_text(
            """from forge import FailureStrategy, FunctionTask, Workflow

attempt_count = 0
def flaky(ctx):
    global attempt_count
    attempt_count += 1
    if attempt_count < 2:
        raise RuntimeError("Transient blip")
    return "recovered"

def get_workflow():
    t = FunctionTask(
        "flaky_step",
        fn=flaky,
        max_retries=2,
        failure_strategy=FailureStrategy.RETRY,
    )
    wf = Workflow(name="RetryWorkflow")
    wf.add_task(t)
    return wf
""",
            encoding="utf-8",
        )
        db_path = tmp_path / "retry.db"
        run_command(file_path, db_path=db_path, quiet=True)

        store = ExecutionStore.create(db_path)
        runs = store.list_workflow_runs()
        assert len(runs) == 1
        run_id = runs[0].run_id
        store.close()

        code = inspect_command(run_id=run_id, db_path=db_path)
        assert code == 0
        captured = capsys.readouterr()
        assert "attempts: 2" in captured.out
        assert "Attempt #1: [FAILED]" in captured.out
        assert "Attempt #2: [SUCCESS]" in captured.out
        assert "Transient blip" in captured.out


# ── Main Entrypoint & Parser Tests ───────────────────────────────────────────

class TestMainEntrypoint:
    def test_build_parser_structure(self):
        parser = build_parser()
        assert parser.prog == "forge"

    def test_main_no_arguments_prints_help(self, capsys):
        code = main([])
        assert code == 0
        captured = capsys.readouterr()
        assert "usage: forge" in captured.out
        assert "run" in captured.out
        assert "validate" in captured.out
        assert "history" in captured.out
        assert "inspect" in captured.out
        assert "status" in captured.out

    def test_main_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "forge 0.2.0" in captured.out

    def test_main_validate_success(self, valid_workflow_file: Path):
        code = main(["validate", str(valid_workflow_file)])
        assert code == 0

    def test_main_validate_failure(self, cyclic_workflow_file: Path):
        code = main(["validate", str(cyclic_workflow_file)])
        assert code == 3

    def test_main_run_success(self, valid_workflow_file: Path):
        code = main(["run", str(valid_workflow_file), "--quiet"])
        assert code == 0

    def test_main_run_failure(self, failing_workflow_file: Path):
        code = main(["run", str(failing_workflow_file), "--quiet"])
        assert code == 1

    def test_main_run_with_db_and_workers(self, valid_workflow_file: Path, tmp_path: Path):
        db_path = tmp_path / "cli_main.db"
        code = main([
            "run",
            str(valid_workflow_file),
            "--db",
            str(db_path),
            "-w",
            "4",
            "-q",
        ])
        assert code == 0
        assert db_path.exists()
        store = ExecutionStore.create(db_path)
        assert store.count_workflow_runs() == 1
        store.close()

    def test_main_history_dispatch(self, valid_workflow_file: Path, tmp_path: Path, capsys):
        db_path = tmp_path / "main_hist.db"
        main(["run", str(valid_workflow_file), "--db", str(db_path), "-q"])
        capsys.readouterr()  # clear buffer

        code = main(["history", "--db", str(db_path)])
        assert code == 0
        captured = capsys.readouterr()
        assert "Forge Execution History" in captured.out
        assert "ValidWorkflow" in captured.out

    def test_main_inspect_dispatch(self, valid_workflow_file: Path, tmp_path: Path, capsys):
        db_path = tmp_path / "main_insp.db"
        main(["run", str(valid_workflow_file), "--db", str(db_path), "-q"])
        store = ExecutionStore.create(db_path)
        run_id = store.list_workflow_runs()[0].run_id
        store.close()
        capsys.readouterr()

        code = main(["inspect", run_id, "--db", str(db_path)])
        assert code == 0
        captured = capsys.readouterr()
        assert f"Workflow Run #{run_id}" in captured.out


# ── Subprocess Integration Tests ─────────────────────────────────────────────

class TestSubprocessCLI:
    def test_python_module_version(self):
        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "--version"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "forge 0.2.0" in proc.stdout

    def test_python_module_help(self):
        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "--help"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "usage: forge" in proc.stdout
        assert "history" in proc.stdout
        assert "inspect" in proc.stdout
        assert "status" in proc.stdout

    def test_python_module_validate(self, valid_workflow_file: Path):
        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "validate", str(valid_workflow_file)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "Workflow 'ValidWorkflow' is valid" in proc.stdout

    def test_python_module_run_failure_exit_code(self, failing_workflow_file: Path):
        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", str(failing_workflow_file)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 1
        assert "FAILED" in proc.stdout

    def test_python_module_history_and_inspect(self, valid_workflow_file: Path, tmp_path: Path):
        db_path = tmp_path / "subproc.db"
        # Run workflow
        run_proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", str(valid_workflow_file), "--db", str(db_path), "-q"],
            capture_output=True,
            text=True,
        )
        assert run_proc.returncode == 0

        # Run history
        hist_proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "history", "--db", str(db_path)],
            capture_output=True,
            text=True,
        )
        assert hist_proc.returncode == 0
        assert "Forge Execution History" in hist_proc.stdout

        store = ExecutionStore.create(db_path)
        run_id = store.list_workflow_runs()[0].run_id
        store.close()

        # Run inspect
        insp_proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "inspect", run_id, "--db", str(db_path)],
            capture_output=True,
            text=True,
        )
        assert insp_proc.returncode == 0
        assert f"Workflow Run #{run_id}" in insp_proc.stdout
        assert "ValidWorkflow" in insp_proc.stdout

    def test_subprocess_exit_code_2_on_syntax_error(self, tmp_path: Path):
        bad_file = tmp_path / "bad_syntax.py"
        bad_file.write_text("def def broken syntax :::", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", str(bad_file)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2
        assert "Error" in proc.stderr
        assert "Traceback" not in proc.stderr

    def test_subprocess_exit_code_2_on_missing_file(self, tmp_path: Path):
        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", str(tmp_path / "absent.py")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2
        assert "Error" in proc.stderr

    def test_subprocess_exit_code_3_on_cyclic_validation(self, cyclic_workflow_file: Path):
        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "validate", str(cyclic_workflow_file)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 3
        assert "Validation error" in proc.stderr
        assert "Traceback" not in proc.stderr


# ── Operational Hardening & Logging Integration Tests ─────────────────────────

class TestCLIOperationalHardening:
    def test_cli_log_level_flag(self, valid_workflow_file: Path, capsys):
        code = main(["--log-level", "DEBUG", "run", str(valid_workflow_file), "-q"])
        assert code == 0

    def test_cli_log_format_flag(self, valid_workflow_file: Path, capsys):
        code = main(["--log-format", "json", "run", str(valid_workflow_file), "-q"])
        assert code == 0

    def test_cli_log_file_flag(self, valid_workflow_file: Path, tmp_path: Path, capsys):
        log_file = tmp_path / "cli_run.log"
        code = main([
            "--log-file",
            str(log_file),
            "--log-level",
            "INFO",
            "run",
            str(valid_workflow_file),
            "-q",
        ])
        assert code == 0
        assert log_file.exists()

    def test_json_stdout_purity_with_debug_logging(self, valid_workflow_file: Path, tmp_path: Path):
        db_path = tmp_path / "debug_clean.db"
        # Run workflow with persistence
        run_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "forge.cli.main",
                "--log-level",
                "DEBUG",
                "run",
                str(valid_workflow_file),
                "--db",
                str(db_path),
                "-q",
            ],
            capture_output=True,
            text=True,
        )
        assert run_proc.returncode == 0

        # Query history --json with DEBUG log level
        hist_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "forge.cli.main",
                "--log-level",
                "DEBUG",
                "--log-format",
                "json",
                "history",
                "--db",
                str(db_path),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert hist_proc.returncode == 0
        # stdout MUST be 100% valid JSON without logging lines mixed in
        data = json.loads(hist_proc.stdout)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["workflow_name"] == "ValidWorkflow"

    def test_json_inspect_purity_with_json_logging(self, valid_workflow_file: Path, tmp_path: Path):
        db_path = tmp_path / "inspect_clean.db"
        main(["run", str(valid_workflow_file), "--db", str(db_path), "-q"])
        store = ExecutionStore.create(db_path)
        run_id = store.list_workflow_runs()[0].run_id
        store.close()

        insp_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "forge.cli.main",
                "--log-level",
                "DEBUG",
                "--log-format",
                "json",
                "inspect",
                run_id,
                "--db",
                str(db_path),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert insp_proc.returncode == 0
        # stdout must parse cleanly
        data = json.loads(insp_proc.stdout)
        assert data["run_id"] == run_id
        assert data["workflow_name"] == "ValidWorkflow"

    def test_status_json_purity_with_logging(self, tmp_path: Path):
        stat_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "forge.cli.main",
                "--log-level",
                "DEBUG",
                "status",
                "--db",
                str(tmp_path / "nonexistent.db"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert stat_proc.returncode == 0
        data = json.loads(stat_proc.stdout)
        assert data["exists"] is False


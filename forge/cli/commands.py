"""CLI command implementations for Forge."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from forge.cli.loader import load_workflow
from forge.core.engine import Engine
from forge.core.result import WorkflowStatus
from forge.exceptions import (
    CircularDependencyError,
    ForgeError,
    LoadError,
    MissingDependencyError,
    WorkflowSpecError,
)
from forge.persistence import ExecutionStore


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #

def run_command(
    workflow_file: str | Path,
    db_path: str | Path | None = None,
    workers: int | None = None,
    quiet: bool = False,
    parameters: dict[str, Any] | None = None,
) -> int:
    """Execute a workflow and print the execution summary.

    Args:
        workflow_file: Path to the Python or declarative workflow definition file.
        db_path: Optional SQLite database file path for persistence.
        workers: Optional max workers for concurrent task execution.
        quiet: If True, suppress engine output and summary.
        parameters: Optional dictionary of runtime parameters.

    Returns:
        int: 0 on success, 1 on workflow execution failure, 2 on load/config error, 3 on validation error.
    """
    try:
        workflow = load_workflow(workflow_file, parameters=parameters)
    except (CircularDependencyError, MissingDependencyError) as e:
        print(f"Validation error in workflow: {e}", file=sys.stderr)
        return 3
    except LoadError as e:
        if isinstance(e.__cause__, (CircularDependencyError, MissingDependencyError, WorkflowSpecError)):
            print(f"Validation error in workflow: {e}", file=sys.stderr)
            return 3
        print(f"Error loading workflow: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Unexpected error loading workflow: {e}", file=sys.stderr)
        return 2

    store = None
    if db_path is not None:
        # Ensure parent directory exists so SQLite can create the file
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            store = ExecutionStore.create(db_file)
        except Exception as e:
            print(f"Error opening execution store at '{db_path}': {e}", file=sys.stderr)
            return 2

        # Explicit opt-in orphan recovery: only run_command triggers this.
        # forge history / forge inspect never call recover_interrupted_runs()
        # so they cannot accidentally cancel a legitimately-live workflow run.
        try:
            recovered = store.recover_interrupted_runs()
            if recovered and not quiet:
                print(
                    f"[forge] Recovered {len(recovered)} orphaned run(s) from a previous crash.",
                    file=sys.stderr,
                )
        except Exception as e:
            # Recovery is best-effort; a failure must not block the new run.
            import logging as _logging
            _logging.getLogger("forge.cli").warning(
                "Orphan recovery failed (non-fatal): %s", e
            )

    max_workers = workers if (workers is not None and workers > 0) else 1
    engine = Engine(
        verbose=not quiet,
        max_workers=max_workers,
        store=store,
    )

    # ── Signal handling ───────────────────────────────────────────────────────
    # OS signals are caught here at the CLI/application boundary.
    # engine.cancel() is the sole cancellation interface; the Engine itself
    # never installs process-global signal handlers.
    import signal as _signal
    _interrupted = [False]
    _original_sigint = _signal.getsignal(_signal.SIGINT)
    _original_sigterm = _signal.getsignal(_signal.SIGTERM)

    def _graceful_cancel(signum: int, frame: object) -> None:
        _interrupted[0] = True
        if not quiet:
            print(
                f"\n[forge] Signal {signum} received — cancelling workflow...",
                file=sys.stderr,
            )
        engine.cancel()

    _signal.signal(_signal.SIGINT, _graceful_cancel)
    _signal.signal(_signal.SIGTERM, _graceful_cancel)

    try:
        result = engine.run(workflow, parameters=parameters)
        if not quiet:
            print(result.summary())
        if _interrupted[0]:
            return 130  # Convention: 128 + signal number (SIGINT=2 → 130)
        return 0 if result.status == WorkflowStatus.SUCCESS else 1
    except (CircularDependencyError, MissingDependencyError, ForgeError) as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Error executing workflow: {e}", file=sys.stderr)
        return 1
    finally:
        # Restore original signal handlers so the process behaves normally
        # if run_command() is called more than once (e.g. in tests).
        _signal.signal(_signal.SIGINT, _original_sigint)
        _signal.signal(_signal.SIGTERM, _original_sigterm)
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #

def validate_command(
    workflow_file: str | Path,
    parameters: dict[str, Any] | None = None,
) -> int:
    """Validate a workflow definition for cyclic or missing dependencies and parameters.

    Args:
        workflow_file: Path to the Python or declarative workflow definition file.
        parameters: Optional dictionary of runtime parameters.

    Returns:
        int: 0 if workflow is valid, 3 on validation error, 2 on load/syntax error.
    """
    try:
        workflow = load_workflow(workflow_file, parameters=parameters)
    except (CircularDependencyError, MissingDependencyError) as e:
        print(f"Validation error in workflow: {e}", file=sys.stderr)
        return 3
    except LoadError as e:
        if isinstance(e.__cause__, (CircularDependencyError, MissingDependencyError, WorkflowSpecError)):
            print(f"Validation error in workflow: {e}", file=sys.stderr)
            return 3
        print(f"Error loading workflow: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Unexpected error loading workflow: {e}", file=sys.stderr)
        return 2

    try:
        workflow.validate()
        param_msg = f" with parameters ({len(workflow.parameters)})" if workflow.parameters else ""
        print(f"Workflow '{workflow.name}' is valid ({len(workflow.tasks)} tasks{param_msg}).")
        return 0
    except (CircularDependencyError, MissingDependencyError, ForgeError) as e:
        print(f"Validation error in workflow '{workflow.name}': {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Unexpected validation error: {e}", file=sys.stderr)
        return 2


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #

def history_command(
    db_path: str | Path = "forge.db",
    workflow: str | None = None,
    status: str | None = None,
    limit: int = 20,
    output_format: str = "table",
) -> int:
    """List execution history from a SQLite database.

    Args:
        db_path: Path to the SQLite database file.
        workflow: Optional filter by workflow name or workflow ID.
        status: Optional filter by run status (e.g. SUCCESS, FAILED).
        limit: Max number of runs to display (default 20).
        output_format: ``"table"`` (default) or ``"json"``.

    Returns:
        int: 0 on success, 2 on error.
    """
    path = Path(db_path)
    if not path.is_file():
        print(
            f"Error: Database file '{path}' not found.\n"
            f"Run a workflow with '--db {path}' first to start recording execution history.",
            file=sys.stderr,
        )
        return 2

    try:
        store = ExecutionStore.create(path)
    except Exception as e:
        print(f"Error opening database '{path}': {e}", file=sys.stderr)
        return 2

    try:
        runs = store.list_workflow_runs(workflow_name=workflow, status=status, limit=limit)
        if not runs and workflow is not None:
            runs = store.list_workflow_runs(workflow_id=workflow, status=status, limit=limit)

        if not runs:
            filter_msg = " matching filter" if (workflow or status) else ""
            if output_format == "json":
                print(json.dumps([]))
            else:
                print(f"No execution history found{filter_msg} in '{path}'.")
            return 0

        if output_format == "json":
            records = []
            for r in runs:
                records.append({
                    "run_id": r.run_id,
                    "workflow_id": r.workflow_id,
                    "workflow_name": r.workflow_name,
                    "status": r.status,
                    "duration_seconds": r.duration_seconds,
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                    "total_tasks": r.total_tasks,
                    "success_count": r.success_count,
                    "failed_count": r.failed_count,
                    "blocked_count": r.blocked_count,
                    "skipped_count": r.skipped_count,
                    "cancelled_count": r.cancelled_count,
                })
            print(json.dumps(records, indent=2))
        else:
            print(f"\nForge Execution History (Database: {path})")
            header = f"{'RUN ID':<16} {'WORKFLOW ID':<22} {'WORKFLOW NAME':<24} {'STATUS':<16} {'DURATION':<10} {'STARTED (UTC)':<20}"
            separator = "-" * len(header)
            print(header)
            print(separator)

            for r in runs:
                dur_str = f"{r.duration_seconds:.2f}s" if r.duration_seconds is not None else "N/A"
                started_clean = r.started_at[:19].replace("T", " ") if r.started_at else "N/A"
                print(
                    f"{r.run_id:<16} {r.workflow_id:<22} {r.workflow_name:<24} {r.status:<16} {dur_str:<10} {started_clean:<20}"
                )
            print(separator + "\n")
        return 0
    except Exception as e:
        print(f"Error querying history: {e}", file=sys.stderr)
        return 2
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #

def inspect_command(
    run_id: str,
    db_path: str | Path = "forge.db",
    output_format: str = "table",
) -> int:
    """Inspect detailed telemetry of a specific workflow execution run.

    Args:
        run_id: Unique execution run identifier (or workflow definition ID).
        db_path: Path to the SQLite database file.
        output_format: ``"table"`` (default) or ``"json"``.

    Returns:
        int: 0 on success, 2 on error.
    """
    path = Path(db_path)
    if not path.is_file():
        print(
            f"Error: Database file '{path}' not found.\n"
            f"Run a workflow with '--db {path}' first to start recording execution history.",
            file=sys.stderr,
        )
        return 2

    try:
        store = ExecutionStore.create(path)
    except Exception as e:
        print(f"Error opening database '{path}': {e}", file=sys.stderr)
        return 2

    try:
        run = store.get_workflow_run(run_id)
        if run is None:
            print(f"Error: Workflow run '{run_id}' not found in '{path}'.", file=sys.stderr)
            return 2

        task_runs = store.get_task_runs(run.run_id)

        if output_format == "json":
            tasks_data = []
            for tr in task_runs:
                attempts_data = []
                attempts = store.get_task_attempts(tr.task_run_id)
                for att in attempts:
                    attempts_data.append({
                        "attempt_number": att.attempt_number,
                        "status": att.status,
                        "duration_seconds": att.duration_seconds,
                        "error_message": att.error_message,
                        "started_at": att.started_at,
                        "finished_at": att.finished_at,
                    })
                tasks_data.append({
                    "task_name": tr.task_name,
                    "task_run_id": tr.task_run_id,
                    "status": tr.status,
                    "attempt_count": tr.attempt_count,
                    "duration_seconds": tr.duration_seconds,
                    "error_message": tr.error_message,
                    "started_at": tr.started_at,
                    "finished_at": tr.finished_at,
                    "attempts": attempts_data,
                })
            record = {
                "run_id": run.run_id,
                "workflow_id": run.workflow_id,
                "workflow_name": run.workflow_name,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "duration_seconds": run.duration_seconds,
                "total_tasks": run.total_tasks,
                "success_count": run.success_count,
                "failed_count": run.failed_count,
                "blocked_count": run.blocked_count,
                "skipped_count": run.skipped_count,
                "cancelled_count": run.cancelled_count,
                "tasks": tasks_data,
            }
            print(json.dumps(record, indent=2))
            return 0

        # Table format
        dur_str = f"{run.duration_seconds:.2f}s" if run.duration_seconds is not None else "N/A"
        started_clean = run.started_at[:19].replace("T", " ") if run.started_at else "N/A"
        finished_clean = run.finished_at[:19].replace("T", " ") if run.finished_at else "Running / Incomplete"

        lines = [
            f"\nWorkflow Run #{run.run_id}",
            f"Workflow ID:  {run.workflow_id}",
            f"Name:         {run.workflow_name}",
            f"Status:       {run.status}",
            f"Started:      {started_clean} UTC",
            f"Finished:     {finished_clean} UTC" if run.finished_at else f"Finished:     {finished_clean}",
            f"Duration:     {dur_str}",
            f"Tasks:        {run.total_tasks} total "
            f"({run.success_count} succeeded, "
            f"{run.failed_count} failed, "
            f"{run.blocked_count} blocked, "
            f"{run.skipped_count} skipped, "
            f"{run.cancelled_count} cancelled)",
            "-------------------------------------------------------",
            "Tasks:",
        ]

        for tr in task_runs:
            status_tag = f"[{tr.status}]"
            t_dur = f"{tr.duration_seconds:.2f}s" if tr.duration_seconds is not None else "N/A"
            t_attempts = f", attempts: {tr.attempt_count}" if tr.attempt_count > 0 else ""
            lines.append(f"  {status_tag:<11} {tr.task_name} (id: {tr.task_run_id}{t_attempts}, {t_dur})")
            if tr.error_message:
                lines.append(f"    Error: {tr.error_message}")

            attempts = store.get_task_attempts(tr.task_run_id)
            if len(attempts) > 1:
                for att in attempts:
                    att_dur = f"{att.duration_seconds:.2f}s" if att.duration_seconds is not None else "N/A"
                    att_err = f" (Error: {att.error_message})" if att.error_message else ""
                    lines.append(f"      Attempt #{att.attempt_number}: [{att.status}] ({att_dur}){att_err}")

        lines.append("=======================================================\n")
        print("\n".join(lines))
        return 0
    except Exception as e:
        print(f"Error inspecting run '{run_id}': {e}", file=sys.stderr)
        return 2
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #

def status_command(
    db_path: str | Path | None = None,
    output_format: str = "table",
) -> int:
    """Display a quick project status dashboard.

    Shows database stats, last 5 runs, and an aggregate success/fail summary.
    If ``db_path`` is ``None``, attempts to read the path from the active
    ForgeConfig (auto-discovery). Returns exit code 0 even if the database
    does not exist yet — this is a diagnostic command, not an execution.

    Args:
        db_path: Path to the SQLite database file.  If None, falls back to
            the config-discovered path or ``forge.db``.
        output_format: ``"table"`` (default) or ``"json"``.

    Returns:
        int: Always 0 (status is informational).
    """
    path = Path(db_path) if db_path is not None else Path("forge.db")

    if not path.is_file():
        if output_format == "json":
            print(json.dumps({
                "database": str(path),
                "exists": False,
                "runs": 0,
                "recent_runs": [],
                "summary": {"success": 0, "failed": 0, "other": 0},
            }, indent=2))
        else:
            print(f"\n  Forge Project Status")
            print(f"  Database: {path} (not found — run a workflow with --db to begin)\n")
        return 0

    try:
        store = ExecutionStore.create(path)
    except Exception as e:
        print(f"Error opening database '{path}': {e}", file=sys.stderr)
        return 0  # still informational

    try:
        db_size_kb = path.stat().st_size / 1024
        total_runs = store.count_workflow_runs()

        # Last 5 runs for dashboard
        recent = store.list_workflow_runs(limit=5)

        # Aggregate counts (fetch all, limited to 1000 for sanity)
        all_runs = store.list_workflow_runs(limit=1000)
        success_count = sum(1 for r in all_runs if r.status == "SUCCESS")
        failed_count = sum(1 for r in all_runs if r.status == "FAILED")
        other_count = total_runs - success_count - failed_count

        if output_format == "json":
            recent_data = [
                {
                    "run_id": r.run_id,
                    "workflow_name": r.workflow_name,
                    "status": r.status,
                    "duration_seconds": r.duration_seconds,
                    "started_at": r.started_at,
                }
                for r in recent
            ]
            print(json.dumps({
                "database": str(path),
                "database_size_kb": round(db_size_kb, 1),
                "exists": True,
                "runs": total_runs,
                "recent_runs": recent_data,
                "summary": {
                    "success": success_count,
                    "failed": failed_count,
                    "other": other_count,
                },
            }, indent=2))
        else:
            print(f"\n  Forge Project Status")
            print(f"  Database: {path} ({db_size_kb:.1f} KB, {total_runs} run(s))\n")

            if not recent:
                print("  No runs recorded yet.\n")
                return 0

            print(f"  {'Last runs':}")
            header = f"  {'RUN ID':<16} {'WORKFLOW NAME':<24} {'STATUS':<12} {'DURATION':<10} {'STARTED (UTC)'}"
            print(header)
            print("  " + "-" * (len(header) - 2))
            for r in recent:
                dur_str = f"{r.duration_seconds:.2f}s" if r.duration_seconds is not None else "N/A"
                started_clean = r.started_at[:16].replace("T", " ") if r.started_at else "N/A"
                print(f"  {r.run_id:<16} {r.workflow_name:<24} {r.status:<12} {dur_str:<10} {started_clean}")
            print()
            print(f"  Summary: {success_count} succeeded, {failed_count} failed, {other_count} other\n")
        return 0
    except Exception as e:
        print(f"Error reading status: {e}", file=sys.stderr)
        return 0
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #

def init_command(target_dir: str | Path = ".") -> int:
    """Initialize a new Forge project with sample configuration and workflow.

    Args:
        target_dir: Path to directory where project files will be created.

    Returns:
        int: 0 on success, 2 on error.
    """
    dest = Path(target_dir).resolve()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating target directory '{dest}': {e}", file=sys.stderr)
        return 2

    config_path = dest / "forge.toml"
    workflow_path = dest / "workflow.json"

    created = []
    skipped = []

    if not config_path.exists():
        config_content = (
            "[forge]\n"
            'database = ".forge/execution.db"\n'
            "workers = 4\n"
            'log_level = "INFO"\n'
            'log_format = "text"\n\n'
            "[logging]\n"
            'level = "INFO"\n'
            'format = "text"\n'
            'file = ".forge/forge.log"\n'
        )
        try:
            config_path.write_text(config_content, encoding="utf-8")
            created.append("forge.toml")
        except Exception as e:
            print(f"Error writing 'forge.toml': {e}", file=sys.stderr)
            return 2
    else:
        skipped.append("forge.toml (already exists)")

    if not workflow_path.exists():
        wf_content = (
            '{\n'
            '  "name": "QuickstartPipeline",\n'
            '  "description": "Canonical beginner workflow: prepare, process, and save report",\n'
            '  "tasks": [\n'
            '    {\n'
            '      "id": "prepare_data",\n'
            '      "type": "file",\n'
            '      "params": {\n'
            '        "operation": "write",\n'
            '        "path": "data/input.json",\n'
            '        "content": "{\\"project\\": \\"Forge\\", \\"status\\": \\"initialized\\"}"\n'
            '      }\n'
            '    },\n'
            '    {\n'
            '      "id": "verify_data",\n'
            '      "type": "file",\n'
            '      "depends_on": [\n'
            '        "prepare_data"\n'
            '      ],\n'
            '      "params": {\n'
            '        "operation": "read",\n'
            '        "path": "data/input.json"\n'
            '      }\n'
            '    },\n'
            '    {\n'
            '      "id": "save_report",\n'
            '      "type": "file",\n'
            '      "depends_on": [\n'
            '        "verify_data"\n'
            '      ],\n'
            '      "params": {\n'
            '        "operation": "write",\n'
            '        "path": "data/report.json",\n'
            '        "content": "{\\"status\\": \\"SUCCESS\\", \\"message\\": \\"Quickstart completed\\"}"\n'
            '      }\n'
            '    }\n'
            '  ]\n'
            '}\n'
        )
        try:
            workflow_path.write_text(wf_content, encoding="utf-8")
            created.append("workflow.json")
        except Exception as e:
            print(f"Error writing 'workflow.json': {e}", file=sys.stderr)
            return 2
    else:
        skipped.append("workflow.json (already exists)")

    print(f"\n[forge] Initialized project in '{dest}'")
    if "forge.toml" in created:
        print("  + Created forge.toml    (Project settings, persistence DB path, worker count)")
    if "workflow.json" in created:
        print("  + Created workflow.json (Starter pipeline: prepare_data -> verify_data -> save_report)")
    for item in skipped:
        print(f"  ~ Skipped {item}")

    print("\nNext steps:")
    print("  1. Preview execution plan: forge plan workflow.json")
    print("  2. Validate DAG structure: forge validate workflow.json")
    print("  3. Execute workflow:       forge run workflow.json")
    print("  4. Inspect run history:    forge history (stored in .forge/ execution store)\n")
    return 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #

def doctor_command(
    db_path: str | Path | None = None,
    output_format: str = "table",
) -> int:
    """Run environment, configuration, and state diagnostics.

    Args:
        db_path: Optional path to SQLite database to verify.
        output_format: "table" or "json".

    Returns:
        int: 0 if healthy, 1 if warnings/errors found.
    """
    from forge import __version__
    from forge.registry.task_registry import TaskRegistry
    from forge.registry.builtins import register_builtin_tasks

    checks = []

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 11)
    checks.append({
        "name": "Python Environment",
        "status": "OK" if py_ok else "ERROR",
        "details": f"Python {py_ver} (>= 3.11 required)",
    })

    # 2. Forge installation
    checks.append({
        "name": "Forge Package",
        "status": "OK",
        "details": f"Forge v{__version__}",
    })

    # 3. Config resolution
    try:
        from forge.config import resolve_config
        cfg = resolve_config()
        cfg_msg = f"Resolved (workers={cfg.workers}, db={cfg.database or 'default'})"
        cfg_ok = True
    except Exception as exc:
        cfg_msg = f"Config error: {exc}"
        cfg_ok = False
        cfg = None
    checks.append({
        "name": "Project Configuration",
        "status": "OK" if cfg_ok else "ERROR",
        "details": cfg_msg,
    })

    # 4. State & Database accessibility
    resolved_db_path = db_path or (cfg.database if cfg and cfg.database else "forge.db")
    target_db = Path(resolved_db_path)
    db_ok = True
    db_details = f"Path '{target_db}' is accessible"
    try:
        target_db.parent.mkdir(parents=True, exist_ok=True)
        test_file = target_db.parent / ".forge_perm_check"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except Exception as exc:
        db_ok = False
        db_details = f"Directory '{target_db.parent}' is not writable: {exc}"

    checks.append({
        "name": "Database & State Directory",
        "status": "OK" if db_ok else "ERROR",
        "details": db_details,
    })

    # 5. Task Registry & Plugin discovery
    reg = TaskRegistry()
    register_builtin_tasks(reg)
    plugin_count = 0
    try:
        from forge.plugins import load_plugins
        plugins = load_plugins(reg)
        plugin_count = len(plugins)
    except Exception:
        pass

    types_str = ", ".join(reg.list_types())
    checks.append({
        "name": "Task Registry & Plugins",
        "status": "OK",
        "details": f"{len(reg)} task type(s) available ({types_str}); {plugin_count} plugin(s) loaded",
    })

    all_ok = all(c["status"] == "OK" for c in checks)

    if output_format == "json":
        print(json.dumps({"healthy": all_ok, "checks": checks}, indent=2))
    else:
        print("\n  Forge Health Diagnostics")
        print("  ========================")
        for c in checks:
            badge = f"[{c['status']}]"
            print(f"  {badge:<9} {c['name']:<28} : {c['details']}")
        print()
        if all_ok:
            print("  System status: All diagnostics PASSED.\n")
        else:
            print("  System status: One or more diagnostics FAILED.\n")

    return 0 if all_ok else 1


# --------------------------------------------------------------------------- #
# tasks
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

def _get_task_type_and_params(task: Any) -> tuple[str, dict[str, Any]]:
    t_type = getattr(task, "task_type", None)
    if not t_type:
        name = task.__class__.__name__
        if name.endswith("Task"):
            name = name[:-4]
        t_type = name.lower()

    raw_params: dict[str, Any] = {}
    if hasattr(task, "params") and isinstance(task.params, dict):
        raw_params = dict(task.params)
    else:
        from enum import Enum
        for attr in ("operation", "path", "source", "destination", "command", "url", "method", "from_upstream"):
            val = getattr(task, attr, None)
            if val is not None:
                if isinstance(val, Enum):
                    val = val.value
                raw_params[attr] = str(val)

    params_summary = {}
    for k, v in raw_params.items():
        if k in ("content", "stdin"):
            params_summary[k] = f"<{len(str(v))} chars>"
        else:
            params_summary[k] = v

    return t_type, params_summary


from forge.declarative.parameters import mask_secret_parameters


def plan_command(
    workflow_file: str | Path,
    output_format: str = "table",
    parameters: dict[str, Any] | None = None,
) -> int:
    """Preview execution plan for a workflow without executing tasks.

    Args:
        workflow_file: Path to workflow definition file (.py, .json, .toml, .yaml).
        output_format: "table" or "json".
        parameters: Optional dictionary of runtime parameters.

    Returns:
        int: 0 on success, 2 on load/config error, 3 on validation error.
    """
    try:
        workflow = load_workflow(workflow_file, parameters=parameters)
    except (CircularDependencyError, MissingDependencyError) as e:
        print(f"Validation error in workflow: {e}", file=sys.stderr)
        return 3
    except LoadError as e:
        if isinstance(e.__cause__, (CircularDependencyError, MissingDependencyError, WorkflowSpecError)):
            print(f"Validation error in workflow: {e}", file=sys.stderr)
            return 3
        print(f"Error loading workflow: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Unexpected error loading workflow: {e}", file=sys.stderr)
        return 2

    try:
        batches = workflow.get_execution_batches()
    except (CircularDependencyError, MissingDependencyError) as e:
        print(f"Validation error in workflow DAG: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Error computing execution plan: {e}", file=sys.stderr)
        return 2

    total_tasks = len(workflow.tasks)
    total_batches = len(batches)
    masked_params = mask_secret_parameters(workflow.parameters)

    formatted_batches = []
    task_counter = 1
    for batch_idx, batch in enumerate(batches, start=1):
        batch_tasks = []
        for task in batch:
            deps = sorted([d.task_id for d in task.dependencies])
            t_type, params_summary = _get_task_type_and_params(task)

            task_info = {
                "step": task_counter,
                "task_id": task.task_id,
                "task_type": t_type,
                "depends_on": deps,
                "params": params_summary,
            }
            batch_tasks.append(task_info)
            task_counter += 1
        formatted_batches.append({
            "batch_number": batch_idx,
            "tasks": batch_tasks,
        })

    if output_format == "json":
        plan_data = {
            "workflow_id": workflow.workflow_id,
            "workflow_name": workflow.name,
            "description": workflow.description or "",
            "parameters": masked_params,
            "total_tasks": total_tasks,
            "total_batches": total_batches,
            "valid": True,
            "batches": formatted_batches,
        }
        print(json.dumps(plan_data, indent=2))
        return 0

    print(f"\nWorkflow Plan: {workflow.name}")
    print("=" * (15 + len(workflow.name)))
    if workflow.description:
        print(f"Description: {workflow.description}")

    if masked_params:
        print("\nParameters:")
        for k, v in masked_params.items():
            print(f"  {k:<16} = {v!r}")

    print(f"\nExecution Plan ({total_tasks} tasks across {total_batches} batch{'es' if total_batches != 1 else ''}):\n")


    for b in formatted_batches:
        print(f"  Batch {b['batch_number']}:")
        for t in b["tasks"]:
            deps_str = ", ".join(t["depends_on"]) if t["depends_on"] else "(none)"
            print(f"    {t['step']}. {t['task_id']}")
            print(f"       type:       {t['task_type']}")
            print(f"       depends on: {deps_str}")
            if t["params"]:
                p_str = ", ".join(f"{k}={v!r}" for k, v in t["params"].items())
                print(f"       parameters: {p_str}")
        print()

    print("Preflight Safety Summary:")
    print("  [OK] Execution DAG is valid (no cycles, no missing dependencies)")
    print(f"  [OK] {total_tasks} tasks scheduled for execution")
    print("  [OK] Dry run complete - no side effects created, no history stored\n")
    return 0


# --------------------------------------------------------------------------- #
# tasks
# --------------------------------------------------------------------------- #

def tasks_command(output_format: str = "table") -> int:
    """List available task types in the system with detailed schemas and examples.

    Args:
        output_format: "table" or "json".

    Returns:
        int: 0
    """
    from forge.registry.task_registry import TaskRegistry
    from forge.registry.builtins import register_builtin_tasks

    reg = TaskRegistry()
    register_builtin_tasks(reg)
    try:
        from forge.plugins import load_plugins
        load_plugins(reg)
    except Exception:
        pass

    task_details = {
        "file": {
            "purpose": "Perform atomic filesystem operations.",
            "source": "built-in",
            "operations": ["read", "write", "copy", "move", "delete"],
            "key_params": ["operation", "path", "content", "source", "destination", "encoding"],
            "example": {
                "id": "write_report",
                "type": "file",
                "params": {
                    "operation": "write",
                    "path": "output/report.txt",
                    "content": "Execution completed successfully."
                }
            }
        },
        "shell": {
            "purpose": "Execute OS subprocess commands with stdout/stderr capture.",
            "source": "built-in",
            "operations": ["exec"],
            "key_params": ["command", "cwd", "env", "stdin", "allowed_exit_codes", "timeout"],
            "example": {
                "id": "run_test_suite",
                "type": "shell",
                "params": {
                    "command": "pytest --tb=short",
                    "allowed_exit_codes": [0]
                }
            }
        },
        "http": {
            "purpose": "Execute REST/HTTP requests with status validation.",
            "source": "built-in",
            "operations": ["GET", "POST", "PUT", "DELETE", "PATCH"],
            "key_params": ["url", "method", "headers", "json_data", "expected_status"],
            "example": {
                "id": "fetch_status",
                "type": "http",
                "params": {
                    "url": "https://httpbin.org/get",
                    "method": "GET",
                    "expected_status": [200]
                }
            }
        },
        "function": {
            "purpose": "Execute in-memory Python callables (Python API only).",
            "source": "built-in",
            "operations": ["call"],
            "key_params": ["fn", "description"],
            "example": {
                "id": "process_memory",
                "type": "function",
                "params": {"description": "Custom python function"}
            }
        },
    }

    result = []
    for t_type in reg.list_types():
        info = task_details.get(t_type, {
            "purpose": "Extension plugin task type.",
            "source": "plugin",
            "operations": ["custom"],
            "key_params": ["params"],
            "example": {"id": f"plugin_{t_type}", "type": t_type, "params": {}}
        })
        result.append({
            "type": t_type,
            "source": info["source"],
            "description": info["purpose"],
            "purpose": info["purpose"],
            "operations": info["operations"],
            "key_params": ", ".join(info["key_params"]) if isinstance(info["key_params"], list) else info["key_params"],
            "example": info["example"],
        })

    if output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("\nAvailable Task Types:")
        print("===========================\n")
        for item in result:
            print(f"  * Task Type: {item['type']}  ({item['source']})")
            print(f"  Purpose:    {item['purpose']}")
            print(f"  Operations: {', '.join(item['operations'])}")
            print(f"  Key Params: {item['key_params']}")
            print("  Minimal Example:")
            ex_lines = json.dumps(item["example"], indent=4).splitlines()
            for line in ex_lines:
                print(f"    {line}")
            print()
        print("Use these task types in declarative workflow files (.json / .toml / .yaml).\n")
    return 0


# --------------------------------------------------------------------------- #
# examples
# --------------------------------------------------------------------------- #

def examples_command(
    copy_name: str | None = None,
    show_name: str | None = None,
    target_path: str | Path | None = None,
    output_format: str = "table",
) -> int:
    """List, inspect, or copy runnable workflow examples.

    Args:
        copy_name: Name of example to copy (e.g. "quickstart").
        show_name: Name of example to inspect/show detailed recipe for.
        target_path: Destination path for copy.
        output_format: "table" or "json".

    Returns:
        int: 0 on success, 2 if name not found.
    """
    pkg_resources_dir = Path(__file__).resolve().parent.parent / "resources" / "examples"
    repo_examples_dir = Path(__file__).resolve().parent.parent.parent / "examples"
    examples_dir = pkg_resources_dir if pkg_resources_dir.is_dir() else repo_examples_dir

    catalog = {
        "quickstart": {
            "name": "quickstart",
            "category": "Getting Started",
            "file": examples_dir / "quickstart.json",
            "classification": "Standalone (Runs offline)",
            "summary": "Canonical 3-step pipeline (prepare, verify, save report)",
            "problem": "Verify Forge installation and test basic DAG task chaining.",
            "what_forge_does": [
                "1. prepare_data (file): Writes seed JSON data to data/input.json",
                "2. verify_data (file): Reads data/input.json to verify content",
                "3. save_report (file): Writes summary report to data/report.json"
            ],
            "what_you_need": ["Python 3.11+", "Forge installed"],
            "run_command": "forge run workflow.json",
            "what_you_will_see": "Execution summary with 3 succeeded tasks and report written to data/report.json.",
            "how_to_customize": "Edit target paths or add downstream processing tasks.",
            "what_can_go_wrong": "File write permission issues in target directory."
        },
        "quickstart_python": {
            "name": "quickstart_python",
            "category": "Getting Started",
            "file": examples_dir / "quickstart.py",
            "classification": "Standalone (Runs offline)",
            "summary": "Canonical beginner workflow in Python API format",
            "problem": "Build workflows programmatically using Python code.",
            "what_forge_does": [
                "1. Defines FunctionTask callables in Python",
                "2. Wires DAG dependencies using add_dependency()",
                "3. Executes workflow via Engine()"
            ],
            "what_you_need": ["Python 3.11+", "Forge installed"],
            "run_command": "python quickstart.py",
            "what_you_will_see": "Python execution output and task results.",
            "how_to_customize": "Add custom Python functions and wire them into the DAG.",
            "what_can_go_wrong": "Unhandled exceptions inside custom Python functions."
        },
        "build_test": {
            "name": "build_test",
            "category": "Developer Automation",
            "file": examples_dir / "declarative" / "build_test.json",
            "classification": "Standalone (Runs offline)",
            "summary": "Cross-platform project build and test automation workflow",
            "problem": "Automate project build configuration, test execution, and artifact generation.",
            "what_forge_does": [
                "1. write_config (file): Writes build/config.json",
                "2. run_tests (shell): Runs automated tests via subprocess",
                "3. generate_artifact (file): Creates build/artifact.txt"
            ],
            "what_you_need": ["Python 3.11+", "Shell execution environment"],
            "run_command": "forge run build_test.json",
            "what_you_will_see": "Automated test output and build artifact file.",
            "how_to_customize": "Replace test command with pytest, npm test, or cargo test.",
            "what_can_go_wrong": "Non-zero exit code from test runner stops artifact generation."
        },
        "file_pipeline": {
            "name": "file_pipeline",
            "category": "File Automation",
            "file": examples_dir / "declarative" / "file_pipeline.json",
            "classification": "Standalone (Runs offline)",
            "summary": "Multi-stage file creation, transformation, and copy workflow",
            "problem": "Process raw files, transform contents, and archive output files.",
            "what_forge_does": [
                "1. create_raw_file (file): Writes raw dataset",
                "2. transform_data (file): Writes processed output",
                "3. archive_data (file): Copies file into archive folder"
            ],
            "what_you_need": ["Local filesystem access"],
            "run_command": "forge run file_pipeline.json",
            "what_you_will_see": "Raw, processed, and archived dataset files.",
            "how_to_customize": "Change target directories or add file validation tasks.",
            "what_can_go_wrong": "Missing source file path."
        },
        "backup": {
            "name": "backup",
            "category": "Data & Backup",
            "file": examples_dir / "declarative" / "backup_workflow.json",
            "classification": "Standalone (Runs offline)",
            "summary": "Automated snapshot and archive workflow",
            "problem": "Create database snapshot dumps, back them up, and verify integrity.",
            "what_forge_does": [
                "1. prepare_source (file): Writes database dump snapshot",
                "2. create_backup (file): Copies dump to backup directory",
                "3. verify_backup (file): Reads backup file to verify data"
            ],
            "what_you_need": ["Storage filesystem access"],
            "run_command": "forge run backup_workflow.json",
            "what_you_will_see": "Backup file created and validated.",
            "how_to_customize": "Point source and destination paths to your backup target.",
            "what_can_go_wrong": "Insufficient disk space or missing backup directory."
        },
        "api_pipeline": {
            "name": "api_pipeline",
            "category": "API Integration",
            "file": examples_dir / "declarative" / "api_pipeline.json",
            "classification": "Requires external service",
            "summary": "REST HTTP request client and response storage workflow",
            "problem": "Fetch REST API data with retries and store payload locally.",
            "what_forge_does": [
                "1. fetch_http_data (http): Sends GET request with retries",
                "2. save_api_response (file): Saves JSON payload to file"
            ],
            "what_you_need": ["Active network connection"],
            "run_command": "forge run api_pipeline.json",
            "what_you_will_see": "API JSON response saved to file.",
            "how_to_customize": "Change target URL, HTTP headers, or request payload.",
            "what_can_go_wrong": "Network failure or 4xx/5xx HTTP status code."
        },
        "ml_pipeline": {
            "name": "ml_pipeline",
            "category": "Machine Learning",
            "file": examples_dir / "declarative" / "ml_pipeline.json",
            "classification": "Standalone (Runs offline)",
            "summary": "ML feature generation, validation, and artifact pipeline",
            "problem": "Prepare ML dataset, extract features, and record evaluation metrics.",
            "what_forge_does": [
                "1. prepare_dataset (file): Generates synthetic CSV dataset",
                "2. generate_features (shell): Processes CSV feature columns",
                "3. validate_metrics (file): Writes ml/metrics.json"
            ],
            "what_you_need": ["Python 3.11+"],
            "run_command": "forge run ml_pipeline.json",
            "what_you_will_see": "Extracted features and model metrics file.",
            "how_to_customize": "Wire in pandas/scikit-learn training scripts.",
            "what_can_go_wrong": "Invalid CSV data format."
        },
    }

    if show_name:
        key = show_name.lower().strip()
        if key not in catalog:
            known = ", ".join(sorted(catalog.keys()))
            print(f"Error: Unknown example '{show_name}'. Available examples: {known}", file=sys.stderr)
            return 2
        info = catalog[key]
        print(f"\nForge Recipe: {info['name']} ({info['category']})")
        print("=" * (14 + len(info['name']) + len(info['category'])))
        print(f"Classification:   {info['classification']}")
        print(f"File:             {info['file'].name}")
        print(f"\nPROBLEM:\n  {info['problem']}")
        print("\nWHAT FORGE DOES:")
        for step in info['what_forge_does']:
            print(f"  {step}")
        print("\nWHAT YOU NEED:")
        for req in info['what_you_need']:
            print(f"  - {req}")
        print(f"\nRUN IT:\n  {info['run_command']}")
        print(f"\nWHAT YOU WILL SEE:\n  {info['what_you_will_see']}")
        print(f"\nHOW TO CUSTOMIZE IT:\n  {info['how_to_customize']}")
        print(f"\nWHAT CAN GO WRONG:\n  {info['what_can_go_wrong']}\n")
        return 0

    if copy_name:
        key = copy_name.lower().strip()
        if key not in catalog:
            known = ", ".join(sorted(catalog.keys()))
            print(f"Error: Unknown example '{copy_name}'. Available examples: {known}", file=sys.stderr)
            return 2

        source_file = catalog[key]["file"]
        if not source_file.is_file():
            print(f"Error: Example source file '{source_file}' not found.", file=sys.stderr)
            return 2

        dest = Path(target_path) if target_path else Path.cwd() / source_file.name
        if dest.is_dir():
            dest = dest / source_file.name

        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(source_file.read_bytes())
            print(f"[forge] Copied example '{key}' ({catalog[key]['classification']}) to '{dest}'")
            print(f"\nTo run this example:")
            print(f"  forge plan {dest.name}")
            print(f"  forge validate {dest.name}")
            print(f"  forge run {dest.name}\n")
            return 0
        except Exception as e:
            print(f"Error copying example to '{dest}': {e}", file=sys.stderr)
            return 2

    if output_format == "json":
        out_list = [
            {
                "name": name,
                "category": info["category"],
                "file": info["file"].name,
                "classification": info["classification"],
                "summary": info["summary"],
                "description": info["summary"],
            }
            for name, info in catalog.items()
        ]
        print(json.dumps(out_list, indent=2))
    else:
        print("\nAvailable Runnable Workflow Examples:")
        print("======================================\n")
        current_cat = None
        for name, info in catalog.items():
            if info["category"] != current_cat:
                current_cat = info["category"]
                print(f"  [{current_cat}]")
            print(f"    * {name:<18} ({info['classification']})")
            print(f"      File:    {info['file'].name}")
            print(f"      Summary: {info['summary']}")
            print()
        print("Commands:")
        print("  forge examples --show <name>  : Inspect recipe details (Problem, Steps, Customization)")
        print("  forge examples --copy <name>  : Copy recipe into your project\n")

    return 0



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
        workflow_file: Path to the Python workflow definition file.
        db_path: Optional SQLite database file path for persistence.
        workers: Optional max workers for concurrent task execution.
        quiet: If True, suppress engine output and summary.
        parameters: Optional dictionary of runtime parameters.

    Returns:
        int: 0 on success, 1 on workflow execution failure, 2 on load/config error, 3 on validation error.
    """
    try:
        workflow = load_workflow(workflow_file)
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

def validate_command(workflow_file: str | Path) -> int:
    """Validate a workflow definition for cyclic or missing dependencies.

    Args:
        workflow_file: Path to the Python workflow definition file.

    Returns:
        int: 0 if workflow is valid, 3 on validation error, 2 on load/syntax error.
    """
    try:
        workflow = load_workflow(workflow_file)
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
        print(f"Workflow '{workflow.name}' is valid ({len(workflow.tasks)} tasks).")
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

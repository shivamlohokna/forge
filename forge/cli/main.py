"""Forge CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forge import __version__
from forge.cli.commands import (
    doctor_command,
    examples_command,
    history_command,
    init_command,
    inspect_command,
    plan_command,
    run_command,
    status_command,
    tasks_command,
    validate_command,
)
from forge.config import ConfigError, ForgeConfig, resolve_config
from forge.exceptions import (
    CircularDependencyError,
    LoadError,
    MissingDependencyError,
)
from forge.logging import setup_logging


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    log_parent = argparse.ArgumentParser(add_help=False)
    log_parent.add_argument(
        "--log-level",
        dest="log_level",
        default=argparse.SUPPRESS,
        choices=["DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"],
        type=str.upper,
        help="Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    log_parent.add_argument(
        "--log-format",
        dest="log_format",
        default=argparse.SUPPRESS,
        choices=["text", "json"],
        type=str.lower,
        help="Set logging format (text, json)",
    )
    log_parent.add_argument(
        "--log-file",
        dest="log_file",
        default=argparse.SUPPRESS,
        help="Path to log file destination",
    )

    parser = argparse.ArgumentParser(
        prog="forge",
        description="Forge - Serious Python Workflow Automation and Execution Platform",
        parents=[log_parent],
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"forge {__version__}",
        help="Show Forge version and exit",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── init ─────────────────────────────────────────────────────────────────
    init_parser = subparsers.add_parser(
        "init",
        parents=[log_parent],
        help="Initialize a new Forge project",
        description="Initialize a new Forge project layout with forge.toml and sample workflow.json.",
    )
    init_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Target project directory (default: current directory)",
    )

    # ── run ──────────────────────────────────────────────────────────────────
    run_parser = subparsers.add_parser(
        "run",
        parents=[log_parent],
        help="Execute a workflow",
        description="Execute a workflow from a Python file (.py) or declarative specification (.json, .toml, .yaml) and print the summary report.",
    )
    run_parser.add_argument(
        "file",
        help="Path to the workflow file (.py, .json, .toml, .yaml)",
    )
    run_parser.add_argument(
        "--db",
        dest="db",
        default=None,
        help="Path to SQLite database for execution persistence (overrides forge.toml)",
    )
    run_parser.add_argument(
        "-w",
        "--workers",
        dest="workers",
        type=int,
        default=None,
        help="Number of concurrent worker threads (overrides forge.toml)",
    )
    run_parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        help="Suppress output logging and execution summary",
    )

    # ── validate ─────────────────────────────────────────────────────────────
    validate_parser = subparsers.add_parser(
        "validate",
        parents=[log_parent],
        help="Validate a workflow definition",
        description="Validate a workflow DAG (.py, .json, .toml, .yaml) for missing dependencies and cycles without executing.",
    )
    validate_parser.add_argument(
        "file",
        help="Path to the workflow file (.py, .json, .toml, .yaml)",
    )

    # ── plan ─────────────────────────────────────────────────────────────────
    plan_parser = subparsers.add_parser(
        "plan",
        parents=[log_parent],
        help="Preview execution plan for a workflow",
        description="Dry-run preflight inspection of DAG execution order and task parameters without side effects.",
    )
    plan_parser.add_argument(
        "file",
        help="Path to the workflow file (.py, .json, .toml, .yaml)",
    )
    plan_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Output execution plan as JSON",
    )

    # ── history ──────────────────────────────────────────────────────────────
    history_parser = subparsers.add_parser(
        "history",
        parents=[log_parent],
        help="List execution history",
        description="Display a tabular summary of past workflow execution runs.",
    )
    history_parser.add_argument(
        "--db",
        dest="db",
        default=None,
        help="Path to SQLite database (overrides forge.toml; default: forge.db)",
    )
    history_parser.add_argument(
        "-w",
        "--workflow",
        dest="workflow",
        default=None,
        help="Filter runs by workflow name or workflow ID",
    )
    history_parser.add_argument(
        "-s",
        "--status",
        dest="status",
        default=None,
        help="Filter runs by execution status (e.g. SUCCESS, FAILED)",
    )
    history_parser.add_argument(
        "-n",
        "--limit",
        dest="limit",
        type=int,
        default=20,
        help="Maximum number of runs to display (default: 20)",
    )
    history_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Output results as JSON",
    )

    # ── inspect ───────────────────────────────────────────────────────────────
    inspect_parser = subparsers.add_parser(
        "inspect",
        parents=[log_parent],
        help="Inspect a workflow run",
        description="Display detailed execution telemetry and task results for a run.",
    )
    inspect_parser.add_argument(
        "run_id",
        help="Unique execution run ID (or workflow definition ID)",
    )
    inspect_parser.add_argument(
        "--db",
        dest="db",
        default=None,
        help="Path to SQLite database (overrides forge.toml; default: forge.db)",
    )
    inspect_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Output results as JSON",
    )

    # ── status ────────────────────────────────────────────────────────────────
    status_parser = subparsers.add_parser(
        "status",
        parents=[log_parent],
        help="Show project execution status",
        description="Display a summary dashboard of recent workflow runs and execution stats.",
    )
    status_parser.add_argument(
        "--db",
        dest="db",
        default=None,
        help="Path to SQLite database (overrides forge.toml; default: forge.db)",
    )
    status_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Output results as JSON",
    )

    # ── doctor ────────────────────────────────────────────────────────────────
    doctor_parser = subparsers.add_parser(
        "doctor",
        parents=[log_parent],
        help="Check system health and setup",
        description="Run health diagnostics on Python environment, configuration, permissions, and plugins.",
    )
    doctor_parser.add_argument(
        "--db",
        dest="db",
        default=None,
        help="Path to SQLite database to check",
    )
    doctor_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Output diagnostics as JSON",
    )

    # ── tasks ─────────────────────────────────────────────────────────────────
    tasks_parser = subparsers.add_parser(
        "tasks",
        parents=[log_parent],
        help="List available task types",
        description="List built-in and plugin-provided task types available for declarative workflows.",
    )
    tasks_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Output task list as JSON",
    )

    # ── examples ──────────────────────────────────────────────────────────────
    examples_parser = subparsers.add_parser(
        "examples",
        parents=[log_parent],
        help="List or copy workflow examples",
        description="List runnable workflow examples or copy an example into your project.",
    )
    examples_parser.add_argument(
        "-s",
        "--show",
        dest="show",
        default=None,
        help="Inspect detailed recipe information for an example (e.g. quickstart)",
    )
    examples_parser.add_argument(
        "--copy",
        dest="copy",
        default=None,
        help="Name of example to copy into project (e.g. quickstart)",
    )
    examples_parser.add_argument(
        "--target",
        dest="target",
        default=None,
        help="Destination path for copied example",
    )
    examples_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Output examples catalog as JSON",
    )

    return parser


def _history_db(settings: ForgeConfig) -> str:
    """Database path for read-only commands (history / inspect / status / doctor)."""
    if settings.database is not None:
        return settings.database
    if Path(".forge/execution.db").is_file():
        return ".forge/execution.db"
    return "forge.db"


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point.

    Args:
        argv: Optional list of argument strings. Uses sys.argv[1:] if None.

    Returns:
        int: Process exit code (0 for success, 1 for workflow failure, 2 for config/syntax error, 3 for validation error).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = resolve_config(cwd=Path.cwd(), cli_args=args)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    # Wire up standard library logging to resolved Forge settings
    setup_logging(settings)

    try:
        if args.command == "init":
            return init_command(target_dir=args.directory)

        elif args.command == "run":
            db_path = settings.database if settings.database is not None else ".forge/execution.db"
            return run_command(
                workflow_file=args.file,
                db_path=db_path,
                workers=settings.workers,
                quiet=args.quiet,
            )

        elif args.command == "validate":
            return validate_command(workflow_file=args.file)

        elif args.command == "plan":
            return plan_command(
                workflow_file=args.file,
                output_format="json" if args.json else "table",
            )

        elif args.command == "history":
            return history_command(
                db_path=_history_db(settings),
                workflow=args.workflow,
                status=args.status,
                limit=args.limit,
                output_format="json" if args.json else "table",
            )

        elif args.command == "inspect":
            return inspect_command(
                run_id=args.run_id,
                db_path=_history_db(settings),
                output_format="json" if args.json else "table",
            )

        elif args.command == "status":
            return status_command(
                db_path=_history_db(settings),
                output_format="json" if args.json else "table",
            )

        elif args.command == "doctor":
            return doctor_command(
                db_path=args.db or _history_db(settings),
                output_format="json" if args.json else "table",
            )

        elif args.command == "tasks":
            return tasks_command(output_format="json" if args.json else "table")

        elif args.command == "examples":
            return examples_command(
                copy_name=args.copy,
                show_name=args.show,
                target_path=args.target,
                output_format="json" if args.json else "table",
            )

        else:
            parser.print_help()
            return 0
    except (CircularDependencyError, MissingDependencyError) as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 3
    except LoadError as exc:
        if isinstance(exc.__cause__, (CircularDependencyError, MissingDependencyError)):
            print(f"Validation error: {exc}", file=sys.stderr)
            return 3
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

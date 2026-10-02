"""Canonical Forge Beginner Workflow (Python API).

Demonstrates defining a simple 3-stage data pipeline using tasks and dependencies:
  prepare_data -> process_data -> save_report
"""

from __future__ import annotations

import sys
from forge import Engine, FileTask, FunctionTask, ShellTask, Workflow


def create_quickstart_workflow() -> Workflow:
    """Build and return the canonical quickstart workflow."""
    # Stage 1: Prepare data via FileTask
    t1 = FileTask(
        "prepare_data",
        operation="write",
        path="data/input.json",
        content='{"project": "Forge", "environment": "starter", "status": "ready"}',
        description="Creates initial dataset file",
    )

    # Stage 2: Process data via FunctionTask
    t2 = FunctionTask(
        "process_data",
        fn=lambda ctx: {"processed_items": 3, "status": "verified"},
        description="Processes payload in Python context",
    )

    # Stage 3: Save final report via FileTask
    t3 = FileTask(
        "save_report",
        operation="write",
        path="data/report.json",
        content='{"status": "SUCCESS", "message": "Quickstart workflow completed successfully."}',
        description="Writes execution summary report",
    )

    # Wire DAG dependencies: prepare_data -> process_data -> save_report
    t1 >> t2 >> t3

    # Assemble Workflow object
    wf = Workflow("QuickstartPythonPipeline", description="Canonical beginner workflow in Python")
    wf.add_tasks(t3)  # Adding leaf task automatically includes upstream dependencies
    return wf


# Module-level variable contract for `forge run quickstart.py`
workflow = create_quickstart_workflow()

if __name__ == "__main__":
    engine = Engine(verbose=True)
    result = engine.run(workflow)
    print(result.summary())

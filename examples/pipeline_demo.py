"""End-to-end demonstration of Forge V2 with concrete FunctionTask instances."""

import time
from forge import Engine, ExecutionContext, FunctionTask, Workflow


def extract_data(context: ExecutionContext) -> dict:
    print("    [Extract] Simulating fetching raw dataset from source...")
    time.sleep(0.1)
    return {
        "source": "sensor_network",
        "readings": [23.4, 25.1, 22.8, 26.5, 24.0, 28.2],
    }


def clean_data(context: ExecutionContext) -> list[float]:
    raw_payload = context.get_upstream_result("Extract")
    print(f"    [Clean] Received {len(raw_payload['readings'])} readings from {raw_payload['source']}.")
    # Filter anomalies and round
    cleaned = [round(r, 1) for r in raw_payload["readings"] if 10.0 <= r <= 40.0]
    return cleaned


def compute_metrics(context: ExecutionContext) -> dict:
    readings = context.get_upstream_result("Clean")
    total = sum(readings)
    count = len(readings)
    avg = round(total / count, 2) if count > 0 else 0.0
    print(f"    [Compute] Analyzed {count} points. Avg: {avg}, Max: {max(readings)}")
    return {"count": count, "total": total, "average": avg, "peak": max(readings)}


def format_report(context: ExecutionContext) -> str:
    metrics = context.get_upstream_result("Compute")
    report = (
        f"=== Daily Sensor Report ===\n"
        f"Sample Size: {metrics['count']} readings\n"
        f"Average Val: {metrics['average']}\n"
        f"Peak Value:  {metrics['peak']}"
    )
    return report


def backup_raw_archive(context: ExecutionContext) -> str:
    raw_payload = context.get_upstream_result("Extract")
    print(f"    [Backup] Archiving raw batch from {raw_payload['source']} to storage...")
    return f"Archived {len(raw_payload['readings'])} records."


def get_workflow() -> Workflow:
    """Build and return a fresh Telemetry ETL & Reporting Pipeline workflow."""
    # 1. Define Concrete Tasks
    t_extract = FunctionTask("Extract", fn=extract_data, description="Fetch raw telemetry")
    t_clean = FunctionTask("Clean", fn=clean_data, description="Filter outlier readings")
    t_compute = FunctionTask("Compute", fn=compute_metrics, description="Calculate mean and max")
    t_report = FunctionTask("Report", fn=format_report, description="Render formatted report")
    t_backup = FunctionTask("Backup", fn=backup_raw_archive, description="Archive raw stream")

    # 2. Wire the DAG
    # Pipeline: Extract -> Clean -> Compute -> Report
    # Branch:   Extract -> Backup (runs independently in parallel tier)
    t_extract >> t_clean >> t_compute >> t_report
    t_extract >> t_backup

    # 3. Assemble Workflow
    workflow = Workflow(
        name="Telemetry ETL & Reporting Pipeline",
        description="End-to-end data processing workflow for sensor readings",
    )
    # Adding downstream tasks pulls in dependencies automatically!
    workflow.add_tasks(t_report, t_backup)
    return workflow


def main():
    workflow = get_workflow()

    # Execute Workflow via Engine
    engine = Engine(verbose=True)
    result = engine.run(workflow)

    # Output Inspection
    print(result.summary())

    final_report = result.get_task_result("Report").output
    print(f"\nFinal Generated Output:\n{final_report}")


if __name__ == "__main__":
    main()


"""End-to-end pipeline combining FunctionTask and FileTask in Forge V2."""

from pathlib import Path
from forge import Engine, ExecutionContext, FileTask, FunctionTask, Workflow


def generate_sales_data(context: ExecutionContext) -> dict:
    print("    [SalesData] Generating daily transaction summary...")
    return {
        "date": "2026-09-06",
        "total_revenue": 14250.75,
        "orders_count": 128,
        "top_product": "Forge Pro License",
    }


def format_markdown_report(context: ExecutionContext) -> str:
    sales = context.get_upstream_result("GenerateData")
    print(f"    [FormatReport] Formatting report for revenue=${sales['total_revenue']}...")
    report = (
        f"# Daily Executive Sales Report\n\n"
        f"- **Date**: {sales['date']}\n"
        f"- **Total Revenue**: ${sales['total_revenue']:,.2f}\n"
        f"- **Orders Processed**: {sales['orders_count']}\n"
        f"- **Top Performer**: {sales['top_product']}\n"
    )
    return report


def main():
    base_dir = Path("./workspace_demo")

    # 1. Tasks Definition
    t_data = FunctionTask("GenerateData", fn=generate_sales_data)

    # Save raw JSON from upstream GenerateData
    t_save_json = FileTask(
        "SaveRawJSON",
        operation="write",
        path=base_dir / "raw_sales.json",
        description="Persist raw sales payload to disk",
    )

    # Transform into Markdown report
    t_format = FunctionTask("FormatReport", fn=format_markdown_report)

    # Save markdown report to disk
    t_save_report = FileTask(
        "SaveReport",
        operation="write",
        path=base_dir / "sales_report.md",
        description="Write markdown report",
    )

    # Copy report to archive directory
    t_archive = FileTask(
        "ArchiveReport",
        operation="copy",
        source=base_dir / "sales_report.md",
        destination=base_dir / "archive" / "sales_report_20260906.md",
        description="Archive finalized report",
    )

    # 2. Wire the DAG
    # Data flow: GenerateData -> (SaveRawJSON, FormatReport -> SaveReport -> ArchiveReport)
    t_data >> t_save_json
    t_data >> t_format >> t_save_report >> t_archive

    # 3. Assemble Workflow
    wf = Workflow(
        name="Automated Daily Sales Report Pipeline",
        description="Generates, serializes, formats, and archives sales reports",
    )
    wf.add_tasks(t_save_json, t_archive)

    # 4. Execute
    engine = Engine(verbose=True)
    result = engine.run(wf)

    # 5. Output Summary
    print(result.summary())

    saved_md = (base_dir / "sales_report.md").read_text(encoding="utf-8")
    print(f"\nGenerated File Content ({base_dir / 'sales_report.md'}):\n{saved_md}")

    # Cleanup demo files
    import shutil
    shutil.rmtree(base_dir)
    print("[Cleanup] Temporary workspace_demo folder removed cleanly.")


if __name__ == "__main__":
    main()

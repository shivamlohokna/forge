"""Comprehensive demonstration orchestrating all four task primitives:
FunctionTask -> HTTPTask -> FunctionTask -> FileTask -> ShellTask.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from forge import (
    Engine,
    ExecutionContext,
    FileTask,
    FunctionTask,
    HTTPMethod,
    HTTPResult,
    HTTPTask,
    ShellResult,
    ShellTask,
    Workflow,
)


class DemoMockServer(BaseHTTPRequestHandler):
    """Local mock HTTP service providing inventory data."""

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        req = json.loads(body) if body else {}

        # Respond with simulated external inventory records
        resp = {
            "warehouse": req.get("region", "global"),
            "timestamp": "2026-09-06T21:30:00Z",
            "items": [
                {"sku": "FORGE-PRO", "stock": 420, "price": 99.0},
                {"sku": "FORGE-CORE", "stock": 1500, "price": 0.0},
                {"sku": "FORGE-CLOUD", "stock": 85, "price": 299.0},
            ],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode("utf-8"))


def prepare_api_request(context: ExecutionContext) -> dict:
    print("    [1. FunctionTask] Preparing warehouse inventory query payload...")
    return {"region": "us-east-1", "department": "software"}


def process_inventory_response(context: ExecutionContext) -> str:
    print("    [3. FunctionTask] Transforming HTTP response payload into markdown...")
    http_result: HTTPResult = context.get_upstream_result("FetchInventory")
    payload = http_result.json()

    total_value = sum(i["stock"] * i["price"] for i in payload["items"])
    total_units = sum(i["stock"] for i in payload["items"])

    report = (
        f"# Warehouse Inventory Report ({payload['warehouse'].upper()})\n"
        f"- Timestamp: {payload['timestamp']}\n"
        f"- Total Units: {total_units:,}\n"
        f"- Inventory Value: ${total_value:,.2f}\n"
        f"- Total SKUs: {len(payload['items'])}\n"
    )
    return report


def main():
    # 1. Start ephemeral mock server
    server = HTTPServer(("127.0.0.1", 0), DemoMockServer)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_dir = Path("./workspace_full_demo").resolve()
    python_bin = sys.executable

    try:
        # Task 1: FunctionTask prepares payload
        t1_prep = FunctionTask(
            "PrepareQuery",
            fn=prepare_api_request,
            description="Assembles query payload",
        )

        # Task 2: HTTPTask sends POST request to external service
        t2_http = HTTPTask(
            "FetchInventory",
            url=f"http://127.0.0.1:{port}/inventory",
            method=HTTPMethod.POST,
            description="Calls remote warehouse inventory API",
        )

        # Task 3: FunctionTask processes API JSON response
        t3_process = FunctionTask(
            "FormatReport",
            fn=process_inventory_response,
            description="Transforms API JSON to Markdown report",
        )

        # Task 4: FileTask persists formatted report to disk
        t4_file = FileTask(
            "SaveReport",
            operation="write",
            path=base_dir / "inventory_report.md",
            description="Saves report to disk",
        )

        # Task 5: ShellTask executes an external process to inspect the generated report
        t5_shell = ShellTask(
            "VerifyReportWithShell",
            command=f'"{python_bin}" -c "print(open(\'inventory_report.md\').readline().strip())"',
            cwd=base_dir,
            description="OS subprocess reading first line of output report",
        )

        # Wire DAG:
        # PrepareQuery -> FetchInventory -> FormatReport -> SaveReport -> VerifyReportWithShell
        t1_prep >> t2_http >> t3_process >> t4_file >> t5_shell

        workflow = Workflow(
            name="Full Phase 3 Integration Pipeline",
            description="Orchestrates Function, HTTP, File, and Shell tasks",
        )
        workflow.add_task(t5_shell)

        # Execute
        engine = Engine(verbose=True)
        result = engine.run(workflow)

        print(result.summary())

        shell_output = result.get_task_result("VerifyReportWithShell").output
        print(f"\nShell Process Verification Output: {shell_output.stdout}")

    finally:
        server.shutdown()
        server.server_close()
        import shutil
        if base_dir.exists():
            shutil.rmtree(base_dir)
        print("[Cleanup] Ephemeral HTTP server and demo workspace cleaned up.")


if __name__ == "__main__":
    main()

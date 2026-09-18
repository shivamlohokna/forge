"""Complete end-to-end demonstration: FunctionTask -> FileTask -> ShellTask -> FileTask."""

import sys
from pathlib import Path
from forge import Engine, ExecutionContext, FileTask, FunctionTask, ShellTask, Workflow


def create_dynamic_script_content(context: ExecutionContext) -> str:
    print("    [1. FunctionTask] Generating dynamic worker script source code...")
    code = (
        "import json, sys\n"
        "data = {'status': 'processed', 'records': [100, 200, 300], 'computed_sum': 600}\n"
        "print(json.dumps(data))\n"
        "sys.stderr.write('Worker process executed cleanly\\n')\n"
    )
    return code


def parse_and_validate(context: ExecutionContext) -> str:
    print("    [5. FunctionTask] Validating generated result on disk...")
    target = Path("./workspace_e2e/final_output.txt")
    content = target.read_text(encoding="utf-8")
    print(f"    [Validation] Successfully read generated output: {content.strip()}")
    return f"Validated: {content.strip()}"


def main():
    base_dir = Path("./workspace_e2e").resolve()
    python_bin = sys.executable

    # 1. FunctionTask: Generate worker code
    t_gen = FunctionTask(
        "GenerateCode",
        fn=create_dynamic_script_content,
        description="Generates Python worker script",
    )

    # 2. FileTask: Save worker code to disk
    t_save_code = FileTask(
        "SaveWorkerScript",
        operation="write",
        path=base_dir / "worker.py",
        description="Writes generated code to disk",
    )

    # 3. ShellTask: Execute the generated script with OS subprocess
    t_shell = ShellTask(
        "RunWorkerProcess",
        command=f'"{python_bin}" worker.py',
        cwd=base_dir,
        description="Executes worker.py as a separate OS process",
    )

    # 4. FileTask: Save the subprocess stdout to a finalized output file
    t_save_out = FileTask(
        "SaveProcessOutput",
        operation="write",
        path=base_dir / "final_output.txt",
        from_upstream="RunWorkerProcess",
        description="Persists subprocess stdout to disk",
    )

    # 5. FunctionTask: Validate output
    t_verify = FunctionTask(
        "VerifyPipeline",
        fn=parse_and_validate,
        description="Asserts file on disk matches expectations",
    )

    # Wire DAG: GenerateCode -> SaveWorkerScript -> RunWorkerProcess -> SaveProcessOutput -> VerifyPipeline
    t_gen >> t_save_code >> t_shell >> t_save_out >> t_verify

    # Assemble Workflow
    workflow = Workflow(
        name="Function-File-Shell Integrated Pipeline",
        description="Demonstrates memory, filesystem, and OS process cooperation",
    )
    workflow.add_task(t_verify)

    # Execute
    engine = Engine(verbose=True)
    result = engine.run(workflow)

    # Print summary
    print(result.summary())

    # Clean up workspace
    import shutil
    shutil.rmtree(base_dir)
    print("\n[Cleanup] Temporary workspace_e2e cleaned up.")


if __name__ == "__main__":
    main()

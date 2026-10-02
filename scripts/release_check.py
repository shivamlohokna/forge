#!/usr/bin/env python3
"""Forge Release Candidate Validation Script.

Automates the complete release verification gate:
1. Executes unit and integration test suite.
2. Builds wheel package (.whl).
3. Creates isolated virtual environment.
4. Installs built wheel into isolated virtual environment.
5. Executes Golden Path user journey from clean working directory.
6. Executes Failure Journey user scenarios.
7. Verifies version consistency and packaging metadata.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_step(title: str, cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    print(f"\n[RELEASE CHECK] {title}...")
    work_dir = cwd if cwd is not None else REPO_ROOT
    proc = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"FAILED: {title}")
        print("STDOUT:", proc.stdout)
        print("STDERR:", proc.stderr)
        sys.exit(proc.returncode)
    print(f"PASSED: {title}")
    return proc


def main() -> int:
    print("=======================================================")
    print("      FORGE RELEASE CANDIDATE VALIDATION SUITE         ")
    print("=======================================================")

    # Step 1: Run pytest
    run_step("1. Running complete pytest test suite", [sys.executable, "-m", "pytest", "--tb=short"])

    # Step 2: Build wheel package
    dist_dir = REPO_ROOT / "dist"
    shutil.rmtree(dist_dir, ignore_errors=True)
    run_step("2. Building Wheel package", [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", "dist", "."])

    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        print("ERROR: No wheel file created in dist/")
        return 1
    wheel_file = wheels[0]
    print(f"   Created wheel: {wheel_file.name}")

    # Step 3: Create isolated virtual environment & install wheel
    with tempfile.TemporaryDirectory() as tmp_env_dir:
        venv_dir = Path(tmp_env_dir) / "venv"
        run_step("3. Creating clean virtual environment", [sys.executable, "-m", "venv", str(venv_dir)])

        if sys.platform == "win32":
            py_bin = venv_dir / "Scripts" / "python.exe"
            forge_bin = venv_dir / "Scripts" / "forge.exe"
        else:
            py_bin = venv_dir / "bin" / "python"
            forge_bin = venv_dir / "bin" / "forge"

        run_step("4. Installing wheel into clean virtual environment", [str(py_bin), "-m", "pip", "install", str(wheel_file)])

        # Step 4: Verify installed package version and CLI
        res = run_step("5. Verifying installed package --version", [str(forge_bin), "--version"])
        assert "forge 0.2.0" in res.stdout

        # Step 5: Execute Golden Path from clean directory
        with tempfile.TemporaryDirectory() as clean_user_dir:
            user_dir = Path(clean_user_dir)
            print("\n[RELEASE CHECK] 6. Testing Golden Path in clean user directory...")

            run_step("   - forge init", [str(forge_bin), "init"], cwd=user_dir)
            run_step("   - forge validate workflow.json", [str(forge_bin), "validate", "workflow.json"], cwd=user_dir)
            run_step("   - forge run workflow.json", [str(forge_bin), "run", "workflow.json"], cwd=user_dir)
            run_step("   - forge history", [str(forge_bin), "history"], cwd=user_dir)
            
            res_hist = run_step("   - forge history --json", [str(forge_bin), "history", "--json"], cwd=user_dir)
            runs = json.loads(res_hist.stdout)
            run_id = runs[0]["run_id"]

            run_step(f"   - forge inspect {run_id}", [str(forge_bin), "inspect", run_id], cwd=user_dir)
            run_step("   - forge doctor", [str(forge_bin), "doctor"], cwd=user_dir)
            run_step("   - forge tasks", [str(forge_bin), "tasks"], cwd=user_dir)
            run_step("   - forge examples --copy build_test", [str(forge_bin), "examples", "--copy", "build_test"], cwd=user_dir)
            run_step("   - forge run build_test.json", [str(forge_bin), "run", "build_test.json"], cwd=user_dir)

        # Step 6: Failure Journey verification
        with tempfile.TemporaryDirectory() as fail_dir:
            user_fail_dir = Path(fail_dir)
            print("\n[RELEASE CHECK] 7. Testing Failure Journeys...")
            
            # Missing file -> Exit code 2
            p = subprocess.run([str(forge_bin), "run", "nonexistent.json"], cwd=str(user_fail_dir), capture_output=True, text=True)
            assert p.returncode == 2
            print("   - Missing file exit code 2: OK")

            # Failing task -> Exit code 1
            fail_wf = user_fail_dir / "fail.json"
            fail_wf.write_text(json.dumps({
                "name": "FailWF",
                "tasks": [{"id": "broken", "type": "shell", "params": {"command": 'python -c "import sys; sys.exit(1)"'}}],
            }), encoding="utf-8")
            p = subprocess.run([str(forge_bin), "run", "fail.json"], cwd=str(user_fail_dir), capture_output=True, text=True)
            assert p.returncode == 1
            print("   - Task failure exit code 1: OK")

    print("\n=======================================================")
    print("   RELEASE CANDIDATE VALIDATION PASSED SUCCESSFULLY!    ")
    print("=======================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())

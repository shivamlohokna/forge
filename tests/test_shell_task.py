"""Comprehensive unit and integration tests for ShellTask."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

from forge import (
    Engine,
    ExecutionContext,
    FailureStrategy,
    FunctionTask,
    ShellResult,
    ShellTask,
    TaskStatus,
    Workflow,
)


class TestShellTask(unittest.TestCase):

    def setUp(self):
        self.engine = Engine(verbose=False)
        self.python_bin = sys.executable

    def test_basic_stdout_capture(self):
        cmd = f'"{self.python_bin}" -c "print(\'forge_shell_ok\')"'
        task = ShellTask("EchoTask", command=cmd)

        wf = Workflow("Echo WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        tr = result.get_task_result("EchoTask")
        shell_res: ShellResult = tr.output

        self.assertEqual(shell_res.exit_code, 0)
        self.assertEqual(shell_res.stdout, "forge_shell_ok")
        self.assertEqual(shell_res.stderr, "")
        self.assertTrue(shell_res.is_success)
        self.assertEqual(shell_res["stdout"], "forge_shell_ok")

    def test_command_failure_on_nonzero_exit(self):
        cmd = f'"{self.python_bin}" -c "import sys; sys.stderr.write(\'fatal_boom\'); sys.exit(3)"'
        task = ShellTask("FailingCmd", command=cmd)

        wf = Workflow("Fail WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_failed)
        tr = result.get_task_result("FailingCmd")
        self.assertTrue(tr.is_failed)
        self.assertIn("exited with code 3", tr.error_message)
        self.assertIn("fatal_boom", tr.error_message)

    def test_allowed_exit_codes(self):
        cmd = f'"{self.python_bin}" -c "import sys; print(\'tolerated\'); sys.exit(2)"'
        task = ShellTask("ToleratedCmd", command=cmd, allowed_exit_codes=[0, 2])

        wf = Workflow("Allowed Code WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        shell_res = result.get_task_result("ToleratedCmd").output
        self.assertEqual(shell_res.exit_code, 2)
        self.assertEqual(shell_res.stdout, "tolerated")

    def test_environment_variables_injection(self):
        cmd = (
            f'"{self.python_bin}" -c "'
            f'import os; '
            f'print(os.environ.get(\'CUSTOM_KEY\') + \':\' + os.environ.get(\'FORGE_TASK_NAME\'))"'
        )
        task = ShellTask("EnvTask", command=cmd, env={"CUSTOM_KEY": "CUSTOM_VAL"})

        wf = Workflow("Env WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        shell_res = result.get_task_result("EnvTask").output
        self.assertEqual(shell_res.stdout, "CUSTOM_VAL:EnvTask")

    def test_working_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir).resolve()
            cmd = f'"{self.python_bin}" -c "import os; print(os.getcwd())"'
            task = ShellTask("CwdTask", command=cmd, cwd=temp_path)

            wf = Workflow("Cwd WF").add_task(task)
            result = self.engine.run(wf)

            self.assertTrue(result.is_success)
            shell_res = result.get_task_result("CwdTask").output
            self.assertEqual(Path(shell_res.stdout).resolve(), temp_path)

    def test_stdin_input_direct(self):
        cmd = f'"{self.python_bin}" -c "import sys; print(\'received:\' + sys.stdin.read().strip())"'
        task = ShellTask("StdinTask", command=cmd, stdin="forge_piped_data")

        wf = Workflow("Stdin WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        shell_res = result.get_task_result("StdinTask").output
        self.assertEqual(shell_res.stdout, "received:forge_piped_data")

    def test_upstream_data_flow_to_stdin(self):
        def generate_msg():
            return "message_from_upstream_task"

        t_gen = FunctionTask("GenMsg", fn=generate_msg)
        cmd = f'"{self.python_bin}" -c "import sys; print(\'echo:\' + sys.stdin.read().strip())"'
        t_shell = ShellTask("PipeTask", command=cmd)

        t_gen >> t_shell

        wf = Workflow("Upstream Stdin WF").add_task(t_shell)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        shell_res = result.get_task_result("PipeTask").output
        self.assertEqual(shell_res.stdout, "echo:message_from_upstream_task")

    def test_shell_task_timeout(self):
        cmd = f'"{self.python_bin}" -c "import time; time.sleep(2.0)"'
        task = ShellTask("SleepTask", command=cmd, timeout=0.05)

        wf = Workflow("Timeout WF").add_task(task)
        start = time.perf_counter()
        result = self.engine.run(wf)
        elapsed = time.perf_counter() - start

        self.assertTrue(result.is_failed)
        tr = result.get_task_result("SleepTask")
        self.assertTrue(tr.is_failed)
        self.assertIn("timed out", tr.error_message)
        # Verify process was killed promptly
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()

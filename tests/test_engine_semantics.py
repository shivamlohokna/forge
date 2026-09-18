"""Comprehensive behavioral and edge-case tests for the Forge Engine."""

import time
import unittest

from forge import (
    Engine,
    ExecutionContext,
    FailureStrategy,
    FunctionTask,
    TaskStatus,
    Workflow,
    WorkflowStatus,
)


class TestEngineSemantics(unittest.TestCase):

    def setUp(self):
        self.engine = Engine(verbose=False)

    def test_empty_workflow(self):
        wf = Workflow("Empty Workflow")
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(result.total_tasks, 0)
        self.assertEqual(len(result.successful_tasks), 0)

    def test_diamond_dag_success(self):
        """Test classic diamond dependency: A -> (B, C) -> D all succeeding."""
        events = []

        def step_a():
            events.append("A")
            return "from_a"

        def step_b(context: ExecutionContext):
            events.append("B")
            return context.get_upstream_result("A") + "_b"

        def step_c(context: ExecutionContext):
            events.append("C")
            return context.get_upstream_result("A") + "_c"

        def step_d(context: ExecutionContext):
            events.append("D")
            return f"{context.get_upstream_result('B')}|{context.get_upstream_result('C')}"

        ta = FunctionTask("A", fn=step_a)
        tb = FunctionTask("B", fn=step_b)
        tc = FunctionTask("C", fn=step_c)
        td = FunctionTask("D", fn=step_d)

        # Wire diamond DAG: A -> B, A -> C, B -> D, C -> D
        ta >> tb >> td
        ta >> tc >> td

        wf = Workflow("Diamond Success").add_tasks(ta, tb, tc, td)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(events[0], "A")
        self.assertEqual(set(events[1:3]), {"B", "C"})
        self.assertEqual(events[3], "D")
        self.assertEqual(result.get_task_result("D").output, "from_a_b|from_a_c")

    def test_diamond_dag_partial_failure_with_continue(self):
        """In A -> (B, C) -> D:
        If C fails with CONTINUE:
        - B should succeed.
        - C should fail.
        - D should be BLOCKED because C failed.
        - Workflow should end in PARTIAL_SUCCESS.
        """
        def step_a():
            return "ok_a"

        def step_b():
            return "ok_b"

        def step_c():
            raise RuntimeError("Failure in C")

        def step_d():
            return "ok_d"

        ta = FunctionTask("A", fn=step_a)
        tb = FunctionTask("B", fn=step_b)
        tc = FunctionTask("C", fn=step_c, failure_strategy=FailureStrategy.CONTINUE)
        td = FunctionTask("D", fn=step_d)

        ta >> tb >> td
        ta >> tc >> td

        wf = Workflow("Diamond Partial").add_tasks(ta, tb, tc, td)
        result = self.engine.run(wf)

        self.assertEqual(result.status, WorkflowStatus.PARTIAL_SUCCESS)
        self.assertTrue(result.get_task_result("A").is_success)
        self.assertTrue(result.get_task_result("B").is_success)
        self.assertTrue(result.get_task_result("C").is_failed)
        self.assertTrue(result.get_task_result("D").is_blocked)
        self.assertIn("prerequisite task 'C'", result.get_task_result("D").error_message)

    def test_multi_level_cascade_blocking(self):
        """A -> B -> C -> D:
        If A fails with CONTINUE:
        B, C, and D must all cascade to BLOCKED.
        """
        def fail_a():
            raise ValueError("Root failure")

        def dummy():
            return "ok"

        ta = FunctionTask("A", fn=fail_a, failure_strategy=FailureStrategy.CONTINUE)
        tb = FunctionTask("B", fn=dummy)
        tc = FunctionTask("C", fn=dummy)
        td = FunctionTask("D", fn=dummy)

        ta >> tb >> tc >> td

        wf = Workflow("Cascade Blocking").add_task(td)
        result = self.engine.run(wf)

        self.assertEqual(result.status, WorkflowStatus.FAILED)
        self.assertTrue(result.get_task_result("A").is_failed)
        self.assertTrue(result.get_task_result("B").is_blocked)
        self.assertTrue(result.get_task_result("C").is_blocked)
        self.assertTrue(result.get_task_result("D").is_blocked)

    def test_workflow_rerun_isolation(self):
        """Running the same workflow instance twice must completely reset state."""
        counter = {"runs": 0}

        def increment():
            counter["runs"] += 1
            return counter["runs"]

        task = FunctionTask("Inc", fn=increment)
        wf = Workflow("Rerun WF").add_task(task)

        # Run 1
        res1 = self.engine.run(wf)
        self.assertTrue(res1.is_success)
        self.assertEqual(res1.get_task_result("Inc").output, 1)

        # Run 2
        res2 = self.engine.run(wf)
        self.assertTrue(res2.is_success)
        self.assertEqual(res2.get_task_result("Inc").output, 2)
        # Ensure fresh attempts list in res2
        self.assertEqual(res2.get_task_result("Inc").attempt_count, 1)

    def test_runtime_parameter_injection(self):
        """Test parameters supplied at workflow level and engine.run level."""
        def inspect_params(context: ExecutionContext):
            env = context.get_param("env")
            batch_size = context.get_param("batch_size")
            return f"{env}:{batch_size}"

        task = FunctionTask("ParamsTask", fn=inspect_params)
        wf = Workflow("Params WF", parameters={"env": "staging", "batch_size": 100})
        wf.add_task(task)

        # Override batch_size at execution time
        result = self.engine.run(wf, parameters={"batch_size": 500})
        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("ParamsTask").output, "staging:500")

    def test_telemetry_and_traceback_capture(self):
        """Verify that error types, messages, tracebacks, and durations are captured."""
        def buggy():
            time.sleep(0.01)
            raise ZeroDivisionError("division by zero in task logic")

        task = FunctionTask("Buggy", fn=buggy, failure_strategy=FailureStrategy.CONTINUE)
        wf = Workflow("Telemetry WF").add_task(task)

        result = self.engine.run(wf)
        tr = result.get_task_result("Buggy")

        self.assertTrue(tr.is_failed)
        self.assertIn("ZeroDivisionError", tr.error_traceback)
        self.assertIn("division by zero", tr.error_message)
        self.assertGreater(tr.duration_seconds, 0.0)
        self.assertEqual(len(tr.attempts), 1)

        attempt = tr.attempts[0]
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.status, TaskStatus.FAILED)
        self.assertIn("ZeroDivisionError", attempt.error_traceback)

    def test_timeout_does_not_block_engine(self):
        """Verify engine does not block waiting for a lingering timed-out thread."""
        def blocking_thread():
            time.sleep(1.0)
            return "done"

        task = FunctionTask("HangingTask", fn=blocking_thread, timeout=0.05)
        wf = Workflow("NonBlockingTimeoutWF").add_task(task)

        start = time.perf_counter()
        result = self.engine.run(wf)
        elapsed = time.perf_counter() - start

        self.assertTrue(result.is_failed)
        self.assertIn("timed out", result.get_task_result("HangingTask").error_message)
        # Should finish around ~0.05s, definitely well below 0.5s
        self.assertLess(elapsed, 0.5)



if __name__ == "__main__":
    unittest.main()

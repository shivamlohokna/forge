"""Unit and integration tests for Forge V2 Core."""

import time
import unittest

from forge.core import (
    Engine,
    ExecutionContext,
    FailureStrategy,
    Task,
    TaskStatus,
    Workflow,
    WorkflowStatus,
)
from forge.exceptions import CircularDependencyError, MissingDependencyError


class ProduceDataTask(Task):
    def execute(self, context: ExecutionContext):
        return {"rows": [1, 2, 3]}


class ConsumeDataTask(Task):
    def execute(self, context: ExecutionContext):
        upstream = context.get_upstream_result("Produce")
        return f"Processed {len(upstream['rows'])} rows"


class FlakyTask(Task):
    def __init__(self, name: str, fail_times: int = 1, **kwargs):
        super().__init__(name, **kwargs)
        self.fail_times = fail_times

    def execute(self, context: ExecutionContext):
        if context.attempt <= self.fail_times:
            raise RuntimeError(f"Simulated error on attempt {context.attempt}")
        return "Finally succeeded!"


class TimeoutTask(Task):
    def execute(self, context: ExecutionContext):
        time.sleep(0.3)
        return "Done"


class TestForgeCore(unittest.TestCase):

    def setUp(self):
        self.engine = Engine(verbose=False)

    def test_task_dependencies_and_operators(self):
        t1 = ProduceDataTask("T1")
        t2 = ConsumeDataTask("T2")
        t3 = ConsumeDataTask("T3")

        t1 >> t2 >> t3
        self.assertIn(t1, t2.dependencies)
        self.assertIn(t2, t3.dependencies)

    def test_workflow_cycle_detection(self):
        c1 = ProduceDataTask("C1")
        c2 = ProduceDataTask("C2")
        c1 >> c2 >> c1

        wf = Workflow("Cycle WF")
        wf.add_tasks(c1, c2)

        with self.assertRaises(CircularDependencyError):
            wf.validate()

    def test_workflow_missing_dependency(self):
        m1 = ProduceDataTask("M1")
        m2 = ProduceDataTask("M2")
        m1.add_dependency(m2)

        wf = Workflow("Missing WF")
        wf.add_task(m1, auto_add_dependencies=False)

        with self.assertRaises(MissingDependencyError):
            wf.validate()

    def test_data_pipeline_execution(self):
        t1 = ProduceDataTask("Produce")
        t2 = ConsumeDataTask("Consume")
        t1 >> t2

        wf = Workflow("Data Pipeline")
        wf.add_task(t2)

        result = self.engine.run(wf)
        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("Consume").output, "Processed 3 rows")

    def test_retry_strategy(self):
        flaky = FlakyTask(
            "Flaky",
            fail_times=2,
            max_retries=3,
            retry_delay=0.01,
            failure_strategy=FailureStrategy.RETRY,
        )
        wf = Workflow("Retry WF")
        wf.add_task(flaky)

        result = self.engine.run(wf)
        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("Flaky").attempt_count, 3)

    def test_stop_strategy_and_cascade_blocked(self):
        bad_task = FlakyTask("BadTask", fail_times=10, failure_strategy=FailureStrategy.STOP)
        downstream = ConsumeDataTask("Downstream")
        bad_task >> downstream

        wf = Workflow("Stop WF")
        wf.add_task(downstream)

        result = self.engine.run(wf)
        self.assertTrue(result.is_failed)
        self.assertTrue(result.get_task_result("BadTask").is_failed)
        self.assertTrue(result.get_task_result("Downstream").is_blocked)

    def test_skip_strategy(self):
        skip_task = FlakyTask("SkipMe", fail_times=10, failure_strategy=FailureStrategy.SKIP)
        independent = ProduceDataTask("Independent")

        wf = Workflow("Skip WF")
        wf.add_tasks(skip_task, independent)

        result = self.engine.run(wf)
        self.assertTrue(result.get_task_result("SkipMe").is_skipped)
        self.assertTrue(result.get_task_result("Independent").is_success)

    def test_task_timeout(self):
        timeout_task = TimeoutTask("TimeoutMe", timeout=0.05)
        wf = Workflow("Timeout WF")
        wf.add_task(timeout_task)

        result = self.engine.run(wf)
        self.assertTrue(result.is_failed)
        self.assertIn("timed out", result.get_task_result("TimeoutMe").error_message)


if __name__ == "__main__":
    unittest.main()

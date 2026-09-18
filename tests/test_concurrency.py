"""Tests for Phase 4 Concurrency, Parallel Execution, Cancellation, and Events."""

import time
import unittest

from forge import (
    Engine,
    EventType,
    ExecutionContext,
    FunctionTask,
    SequentialExecutor,
    TaskStatus,
    ThreadPoolTaskExecutor,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)


class TestConcurrencyAndInfrastructure(unittest.TestCase):

    def test_parallel_batch_execution_speedup(self):
        """Verify that independent tasks run concurrently instead of sequentially."""
        def sleep_task():
            time.sleep(0.15)
            return "done"

        t1 = FunctionTask("Task1", fn=sleep_task)
        t2 = FunctionTask("Task2", fn=sleep_task)
        t3 = FunctionTask("Task3", fn=sleep_task)

        # All 3 are independent (same batch)
        wf = Workflow("Parallel WF").add_tasks(t1, t2, t3)

        # Run parallel with 3 workers
        engine_parallel = Engine(verbose=False, max_workers=3)
        start = time.perf_counter()
        result = engine_parallel.run(wf)
        elapsed = time.perf_counter() - start

        self.assertTrue(result.is_success)
        self.assertEqual(result.total_tasks, 3)
        # 3 tasks * 0.15s = 0.45s sequentially. Parallel should finish in < 0.30s
        self.assertLess(elapsed, 0.30)

    def test_concurrency_worker_limits(self):
        """Verify max_workers=2 limits parallel workers."""
        active_workers = 0
        peak_workers = 0

        def track_workers():
            nonlocal active_workers, peak_workers
            active_workers += 1
            peak_workers = max(peak_workers, active_workers)
            time.sleep(0.1)
            active_workers -= 1
            return "ok"

        tasks = [FunctionTask(f"T{i}", fn=track_workers) for i in range(4)]
        wf = Workflow("Worker Limit WF").add_tasks(*tasks)

        engine = Engine(verbose=False, max_workers=2)
        result = engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertLessEqual(peak_workers, 2)

    def test_workflow_cancellation(self):
        """Verify cancelling the engine halts pending tasks and marks them CANCELLED."""
        def slow_step():
            time.sleep(0.05)
            return "step1"

        def never_step():
            return "step2"

        t1 = FunctionTask("Slow", fn=slow_step)
        t2 = FunctionTask("Never", fn=never_step)
        t1 >> t2

        wf = Workflow("Cancel WF").add_tasks(t1, t2)
        engine = Engine(verbose=False)

        # Hook to trigger cancellation as soon as task 1 finishes
        class CancelHook:
            def on_task_success(self, task, output):
                engine.cancel()

        engine.add_hook(CancelHook())
        result = engine.run(wf)

        self.assertEqual(result.status, WorkflowStatus.CANCELLED)
        self.assertTrue(result.get_task_result("Slow").is_success)
        self.assertTrue(result.get_task_result("Never").is_cancelled)
        self.assertEqual(len(result.cancelled_tasks), 1)

    def test_lifecycle_event_stream(self):
        """Verify the pub/sub event dispatcher emits structured events."""
        recorded_events: list[WorkflowEvent] = []

        def dummy():
            return "payload"

        task = FunctionTask("SimpleTask", fn=dummy)
        wf = Workflow("Event WF").add_task(task)

        engine = Engine(verbose=False)
        engine.events.subscribe(lambda e: recorded_events.append(e))

        result = engine.run(wf)
        self.assertTrue(result.is_success)

        event_types = [e.event_type for e in recorded_events]
        self.assertIn(EventType.WORKFLOW_STARTED, event_types)
        self.assertIn(EventType.TASK_READY, event_types)
        self.assertIn(EventType.TASK_STARTED, event_types)
        self.assertIn(EventType.TASK_SUCCEEDED, event_types)
        self.assertIn(EventType.WORKFLOW_FINISHED, event_types)

        # Verify structured event properties
        started_event = next(e for e in recorded_events if e.event_type == EventType.WORKFLOW_STARTED)
        self.assertEqual(started_event.workflow_name, "Event WF")

    def test_sequential_executor_parity(self):
        """Verify that SequentialExecutor produces identical results."""
        t1 = FunctionTask("Step1", fn=lambda: 10)
        t2 = FunctionTask("Step2", fn=lambda ctx: ctx.get_upstream_result("Step1") * 2)
        t1 >> t2

        wf = Workflow("Seq WF").add_tasks(t1, t2)
        engine = Engine(verbose=False, executor=SequentialExecutor())
        result = engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("Step2").output, 20)


if __name__ == "__main__":
    unittest.main()

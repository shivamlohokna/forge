"""Tests for concrete FunctionTask execution in Forge V2."""

import unittest

from forge import (
    Engine,
    ExecutionContext,
    FailureStrategy,
    FunctionTask,
    TaskStatus,
    Workflow,
)


class TestFunctionTask(unittest.TestCase):

    def setUp(self):
        self.engine = Engine(verbose=False)

    def test_parameterless_function(self):
        def greet():
            return "hello world"

        task = FunctionTask("Greet", fn=greet)
        wf = Workflow("Greet WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("Greet").output, "hello world")

    def test_function_with_args_and_kwargs(self):
        def add(a, b, multiplier=1):
            return (a + b) * multiplier

        task = FunctionTask("Add", fn=add, fn_args=(10, 20), fn_kwargs={"multiplier": 3})
        wf = Workflow("Add WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("Add").output, 90)

    def test_context_aware_data_pipeline(self):
        # Step 1: Generate numbers
        def generate_data(context: ExecutionContext):
            return [10, 20, 30]

        # Step 2: Multiply by factor
        def multiply_data(context: ExecutionContext):
            numbers = context.get_upstream_result("Generate")
            return [n * 2 for n in numbers]

        # Step 3: Format summary
        def format_summary(context: ExecutionContext):
            doubled = context.get_upstream_result("Multiply")
            total = sum(doubled)
            return f"Processed {len(doubled)} items with sum={total}"

        task_a = FunctionTask("Generate", fn=generate_data)
        task_b = FunctionTask("Multiply", fn=multiply_data)
        task_c = FunctionTask("Format", fn=format_summary)

        # Build DAG
        task_a >> task_b >> task_c

        wf = Workflow("ETL Numbers Pipeline").add_task(task_c)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(
            result.get_task_result("Format").output,
            "Processed 3 items with sum=120",
        )

    def test_function_retry_on_failure(self):
        attempts_tracker = []

        def flaky_fn(context: ExecutionContext):
            attempts_tracker.append(context.attempt)
            if context.attempt < 3:
                raise ValueError(f"Temporary glitch on attempt {context.attempt}")
            return "Success on attempt 3"

        task = FunctionTask(
            "FlakyTask",
            fn=flaky_fn,
            max_retries=3,
            retry_delay=0.01,
            failure_strategy=FailureStrategy.RETRY,
        )

        wf = Workflow("Flaky WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(len(attempts_tracker), 3)
        self.assertEqual(result.get_task_result("FlakyTask").attempt_count, 3)
        self.assertEqual(
            result.get_task_result("FlakyTask").output,
            "Success on attempt 3",
        )


if __name__ == "__main__":
    unittest.main()

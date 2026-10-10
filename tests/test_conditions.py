"""Comprehensive test suite for Forge Phase 7: Conditional Task Execution and Trigger Rules.

Tests cover:
- AST condition evaluator (comparisons, boolean logic, membership, literals, security boundaries)
- Trigger rules (ALL_SUCCESS, ALL_DONE, NONE_FAILED, ONE_SUCCESS, ALL_FAILED)
- Engine execution with conditional tasks (skipping, cascade skipping, teardown/cleanup)
- Declarative JSON/TOML/YAML workflow parsing and schema validation
- CLI plan, run, and examples integration
"""

import os
import json
import tempfile
from pathlib import Path
import pytest

from forge.core.conditions import (
    ConditionEvaluationError,
    ConditionSyntaxError,
    evaluate_condition,
    validate_condition_syntax,
)
from forge.core.engine import Engine
from forge.core.result import WorkflowStatus
from forge.core.task import (
    ExecutionContext,
    FailureStrategy,
    Task,
    TaskStatus,
    TriggerRule,
)
from forge.core.workflow import Workflow
from forge.declarative.loader import load_declarative_workflow
from forge.exceptions import WorkflowSpecError
from forge.tasks.file_task import FileTask
from forge.tasks.function_task import FunctionTask
from forge.tasks.shell_task import ShellTask


# =========================================================================== #
# 1. Unit Tests: AST Condition Evaluator
# =========================================================================== #

class TestASTConditionEvaluator:
    """Tests for safe AST-based condition evaluation."""

    def _ctx(self, params=None, outputs=None):
        return ExecutionContext(
            task_id="test_task",
            task_name="TestTask",
            parameters=params or {},
            outputs=outputs or {},
        )

    def test_unconditional_or_none(self):
        ctx = self._ctx()
        assert evaluate_condition(None, ctx) == (True, "")
        assert evaluate_condition("", ctx) == (True, "")
        assert evaluate_condition("   ", ctx) == (True, "")

    def test_literal_booleans(self):
        ctx = self._ctx()
        assert evaluate_condition(True, ctx) == (True, "")
        assert evaluate_condition(False, ctx)[0] is False
        assert evaluate_condition("true", ctx) == (True, "")
        assert evaluate_condition("True", ctx) == (True, "")
        assert evaluate_condition("false", ctx)[0] is False
        assert evaluate_condition("False", ctx)[0] is False

    def test_template_braces_stripping(self):
        ctx = self._ctx({"env": "prod"})
        assert evaluate_condition("{{ parameters.env == 'prod' }}", ctx) == (True, "")
        assert evaluate_condition("{{ parameters.env == 'staging' }}", ctx)[0] is False

    def test_comparison_operators(self):
        ctx = self._ctx({"count": 10, "threshold": 5})
        assert evaluate_condition("parameters.count > 5", ctx)[0] is True
        assert evaluate_condition("parameters.count >= 10", ctx)[0] is True
        assert evaluate_condition("parameters.count < 20", ctx)[0] is True
        assert evaluate_condition("parameters.count <= 10", ctx)[0] is True
        assert evaluate_condition("parameters.count == 10", ctx)[0] is True
        assert evaluate_condition("parameters.count != 99", ctx)[0] is True
        assert evaluate_condition("parameters.count < parameters.threshold", ctx)[0] is False

    def test_membership_and_lists(self):
        ctx = self._ctx({"role": "admin", "tags": ["prod", "us-east"]})
        assert evaluate_condition("parameters.role in ['admin', 'superuser']", ctx)[0] is True
        assert evaluate_condition("parameters.role not in ['guest', 'anonymous']", ctx)[0] is True
        assert evaluate_condition("'prod' in parameters.tags", ctx)[0] is True
        assert evaluate_condition("'staging' in parameters.tags", ctx)[0] is False

    def test_boolean_logic(self):
        ctx = self._ctx({"is_active": True, "env": "prod", "retries": 3})
        assert evaluate_condition("parameters.is_active and parameters.env == 'prod'", ctx)[0] is True
        assert evaluate_condition("parameters.env == 'dev' or parameters.is_active", ctx)[0] is True
        assert evaluate_condition("not (parameters.env == 'dev')", ctx)[0] is True
        assert evaluate_condition("parameters.is_active and not (parameters.retries < 2)", ctx)[0] is True

    def test_output_references(self):
        ctx = self._ctx(
            params={"target_code": 0},
            outputs={"build_step": {"exit_code": 0, "status": "SUCCESS", "artifacts": ["app.zip"]}},
        )
        assert evaluate_condition("outputs.build_step.exit_code == 0", ctx)[0] is True
        assert evaluate_condition("outputs.build_step.status == 'SUCCESS'", ctx)[0] is True
        assert evaluate_condition("'app.zip' in outputs.build_step.artifacts", ctx)[0] is True
        assert evaluate_condition("outputs.build_step.exit_code == parameters.target_code", ctx)[0] is True
        assert evaluate_condition("outputs.nonexistent.field == 1", ctx)[0] is False

    def test_environment_variables(self, monkeypatch):
        monkeypatch.setenv("FORGE_TEST_ENV", "ENABLED")
        ctx = self._ctx()
        assert evaluate_condition("env.FORGE_TEST_ENV == 'ENABLED'", ctx)[0] is True
        assert evaluate_condition("env.FORGE_TEST_ENV != 'DISABLED'", ctx)[0] is True

    def test_callable_condition(self):
        ctx = self._ctx({"counter": 42})
        assert evaluate_condition(lambda c: c.get_param("counter") == 42, ctx)[0] is True
        assert evaluate_condition(lambda c: c.get_param("counter") == 0, ctx)[0] is False

    def test_security_rejection_of_arbitrary_calls(self):
        ctx = self._ctx()
        with pytest.raises(ConditionEvaluationError):
            evaluate_condition("__import__('os').system('echo pwned')", ctx)

        with pytest.raises(ConditionEvaluationError):
            evaluate_condition("len([1, 2, 3]) == 3", ctx)

    def test_syntax_validation(self):
        validate_condition_syntax("parameters.env == 'prod'")
        validate_condition_syntax("{{ outputs.build.status == 'OK' }}")

        with pytest.raises(ConditionSyntaxError):
            validate_condition_syntax("parameters.env == = 'bad'")

        with pytest.raises(ConditionEvaluationError):
            validate_condition_syntax("eval('1 + 1')")


# =========================================================================== #
# 2. Integration Tests: Trigger Rules
# =========================================================================== #

class TestTriggerRules:
    """Tests for DAG TriggerRule semantics."""

    def test_all_success_default_and_skipped_cascade(self):
        """Under ALL_SUCCESS: skipped upstream causes downstream to be skipped."""
        wf = Workflow("CascadeSkip")
        t1 = FunctionTask("T1", fn=lambda ctx: "data", when=False)
        t2 = FunctionTask("T2", fn=lambda ctx: "downstream")
        t2.add_dependency(t1)
        wf.add_tasks(t1, t2)

        engine = Engine(verbose=False)
        res = engine.run(wf)
        assert res.status == WorkflowStatus.SUCCESS
        assert res.get_task_result("T1").is_skipped
        assert res.get_task_result("T2").is_skipped

    def test_all_done_runs_after_failure(self):
        """Under ALL_DONE: cleanup task executes even when upstream fails."""
        cleanup_ran = []

        def failing_task(ctx):
            raise RuntimeError("Task failed intentionally")

        def cleanup_fn(ctx):
            cleanup_ran.append(True)
            return "cleaned"

        wf = Workflow("CleanupWorkflow")
        t_fail = FunctionTask("FailTask", fn=failing_task, failure_strategy=FailureStrategy.STOP)
        t_clean = FunctionTask("CleanupTask", fn=cleanup_fn, trigger_rule=TriggerRule.ALL_DONE)
        t_clean.add_dependency(t_fail)
        wf.add_tasks(t_fail, t_clean)

        engine = Engine(verbose=False)
        res = engine.run(wf)

        assert res.get_task_result("FailTask").is_failed
        assert res.get_task_result("CleanupTask").is_success
        assert len(cleanup_ran) == 1

    def test_all_done_runs_after_skipped_branch(self):
        """Under ALL_DONE: cleanup task executes when upstream was skipped."""
        wf = Workflow("CleanupAfterSkip")
        t_skip = FunctionTask("SkipTask", fn=lambda ctx: 1, when=False)
        t_clean = FunctionTask("Cleanup", fn=lambda ctx: 2, trigger_rule=TriggerRule.ALL_DONE)
        t_clean.add_dependency(t_skip)
        wf.add_tasks(t_skip, t_clean)

        engine = Engine(verbose=False)
        res = engine.run(wf)
        assert res.status == WorkflowStatus.SUCCESS
        assert res.get_task_result("SkipTask").is_skipped
        assert res.get_task_result("Cleanup").is_success

    def test_none_failed_allows_skipped_dependency(self):
        """Under NONE_FAILED: succeeds when upstream is SUCCESS or SKIPPED."""
        wf = Workflow("NoneFailedWF")
        t1 = FunctionTask("T1", fn=lambda ctx: "ok")
        t2 = FunctionTask("T2", fn=lambda ctx: "skipped", when=False)
        t3 = FunctionTask("T3", fn=lambda ctx: "merged", trigger_rule=TriggerRule.NONE_FAILED)
        t3.add_dependency(t1)
        t3.add_dependency(t2)
        wf.add_tasks(t1, t2, t3)

        engine = Engine(verbose=False)
        res = engine.run(wf)
        assert res.status == WorkflowStatus.SUCCESS
        assert res.get_task_result("T1").is_success
        assert res.get_task_result("T2").is_skipped
        assert res.get_task_result("T3").is_success

    def test_one_success_trigger_rule(self):
        """Under ONE_SUCCESS: task runs if at least one dependency succeeded."""
        wf = Workflow("OneSuccessWF")
        t_fail = FunctionTask("FailTask", fn=lambda ctx: 1 / 0, failure_strategy=FailureStrategy.CONTINUE)
        t_ok = FunctionTask("OkTask", fn=lambda ctx: "good")
        t_down = FunctionTask("Downstream", fn=lambda ctx: "proceed", trigger_rule=TriggerRule.ONE_SUCCESS)
        t_down.add_dependency(t_fail)
        t_down.add_dependency(t_ok)
        wf.add_tasks(t_fail, t_ok, t_down)

        engine = Engine(verbose=False)
        res = engine.run(wf)
        assert res.get_task_result("OkTask").is_success
        assert res.get_task_result("FailTask").is_failed
        assert res.get_task_result("Downstream").is_success

    def test_all_failed_trigger_rule(self):
        """Under ALL_FAILED: incident alert runs only when upstream tasks fail."""
        alert_sent = []

        wf = Workflow("AllFailedAlert")
        t_fail = FunctionTask("BrokenTask", fn=lambda ctx: 1 / 0, failure_strategy=FailureStrategy.CONTINUE)
        t_alert = FunctionTask(
            "SendAlert",
            fn=lambda ctx: alert_sent.append(True),
            trigger_rule=TriggerRule.ALL_FAILED,
        )
        t_alert.add_dependency(t_fail)
        wf.add_tasks(t_fail, t_alert)

        engine = Engine(verbose=False)
        res = engine.run(wf)
        assert res.get_task_result("BrokenTask").is_failed
        assert res.get_task_result("SendAlert").is_success
        assert len(alert_sent) == 1


# =========================================================================== #
# 3. Integration Tests: Declarative Workflows with When and TriggerRule
# =========================================================================== #

class TestDeclarativeConditionalWorkflows:
    """Tests for declarative JSON/TOML/YAML conditional workflows."""

    def test_declarative_branching_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wf_spec = {
                "name": "BranchingTest",
                "parameters": {"environment": "production", "deploy": True},
                "tasks": [
                    {
                        "id": "write_artifact",
                        "type": "file",
                        "params": {"operation": "write", "path": f"{tmp}/artifact.txt", "content": "PKG"},
                    },
                    {
                        "id": "deploy_prod",
                        "type": "file",
                        "depends_on": ["write_artifact"],
                        "when": "{{ parameters.environment == 'production' and parameters.deploy == true }}",
                        "params": {"operation": "write", "path": f"{tmp}/prod.txt", "content": "PROD"},
                    },
                    {
                        "id": "deploy_staging",
                        "type": "file",
                        "depends_on": ["write_artifact"],
                        "when": "{{ parameters.environment == 'staging' }}",
                        "params": {"operation": "write", "path": f"{tmp}/staging.txt", "content": "STAGING"},
                    },
                    {
                        "id": "cleanup",
                        "type": "file",
                        "depends_on": ["deploy_prod", "deploy_staging"],
                        "trigger_rule": "all_done",
                        "params": {"operation": "write", "path": f"{tmp}/done.txt", "content": "DONE"},
                    },
                ],
            }

            wf = load_declarative_workflow(wf_spec)
            engine = Engine(verbose=False)
            res = engine.run(wf)

            assert res.status == WorkflowStatus.SUCCESS
            assert res.get_task_result("write_artifact").is_success
            assert res.get_task_result("deploy_prod").is_success
            assert res.get_task_result("deploy_staging").is_skipped
            assert res.get_task_result("cleanup").is_success

            assert (tmp_path / "prod.txt").exists()
            assert not (tmp_path / "staging.txt").exists()
            assert (tmp_path / "done.txt").exists()

    def test_declarative_branching_staging_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wf_spec = {
                "name": "BranchingStaging",
                "parameters": {"environment": "production"},
                "tasks": [
                    {
                        "id": "step1",
                        "type": "file",
                        "params": {"operation": "write", "path": f"{tmp}/step1.txt", "content": "S1"},
                    },
                    {
                        "id": "deploy_prod",
                        "type": "file",
                        "depends_on": ["step1"],
                        "when": "{{ parameters.environment == 'production' }}",
                        "params": {"operation": "write", "path": f"{tmp}/prod.txt", "content": "P"},
                    },
                    {
                        "id": "deploy_staging",
                        "type": "file",
                        "depends_on": ["step1"],
                        "when": "{{ parameters.environment == 'staging' }}",
                        "params": {"operation": "write", "path": f"{tmp}/staging.txt", "content": "S"},
                    },
                ],
            }

            # Override environment to staging
            wf = load_declarative_workflow(wf_spec, parameters={"environment": "staging"})
            engine = Engine(verbose=False)
            res = engine.run(wf)

            assert res.status == WorkflowStatus.SUCCESS
            assert res.get_task_result("deploy_prod").is_skipped
            assert res.get_task_result("deploy_staging").is_success
            assert not (tmp_path / "prod.txt").exists()
            assert (tmp_path / "staging.txt").exists()

    def test_validation_rejects_invalid_trigger_rule(self):
        spec = {
            "name": "InvalidTrigger",
            "tasks": [
                {
                    "id": "t1",
                    "type": "file",
                    "trigger_rule": "INVALID_RULE_NAME",
                    "params": {"operation": "write", "path": "test.txt", "content": "a"},
                }
            ],
        }
        with pytest.raises(WorkflowSpecError) as exc_info:
            load_declarative_workflow(spec)
        assert "invalid trigger_rule" in str(exc_info.value)

    def test_validation_rejects_malformed_when_expression(self):
        spec = {
            "name": "MalformedWhen",
            "tasks": [
                {
                    "id": "t1",
                    "type": "file",
                    "when": "{{ parameters.env === 'prod' }}",
                    "params": {"operation": "write", "path": "test.txt", "content": "a"},
                }
            ],
        }
        with pytest.raises(WorkflowSpecError) as exc_info:
            load_declarative_workflow(spec)
        assert "invalid condition expression" in str(exc_info.value)


# =========================================================================== #
# 4. Integration Tests: CLI Plan, Run, and Examples
# =========================================================================== #

class TestCLIPlanAndExamplesIntegration:
    """Tests for CLI plan preview and examples catalog with Phase 7 features."""

    def test_plan_command_displays_when_and_trigger(self, capsys):
        from forge.cli.commands import plan_command

        with tempfile.TemporaryDirectory() as tmp:
            wf_file = Path(tmp) / "conditional.json"
            wf_file.write_text(json.dumps({
                "name": "PlanTest",
                "parameters": {"env": "staging"},
                "tasks": [
                    {
                        "id": "prepare",
                        "type": "file",
                        "params": {"operation": "write", "path": "prep.txt", "content": "1"},
                    },
                    {
                        "id": "conditional_task",
                        "type": "file",
                        "depends_on": ["prepare"],
                        "when": "{{ parameters.env == 'prod' }}",
                        "trigger_rule": "all_done",
                        "params": {"operation": "write", "path": "cond.txt", "content": "2"},
                    },
                ],
            }), encoding="utf-8")

            exit_code = plan_command(wf_file)
            assert exit_code == 0
            captured = capsys.readouterr().out
            assert "when:       {{ parameters.env == 'prod' }}" in captured
            assert "trigger:    ALL_DONE" in captured

    def test_plan_command_json_output(self, capsys):
        from forge.cli.commands import plan_command

        with tempfile.TemporaryDirectory() as tmp:
            wf_file = Path(tmp) / "conditional.json"
            wf_file.write_text(json.dumps({
                "name": "PlanJSONTest",
                "tasks": [
                    {
                        "id": "t1",
                        "type": "file",
                        "when": "parameters.run_step == true",
                        "trigger_rule": "all_done",
                        "params": {"operation": "write", "path": "t1.txt", "content": "1"},
                    },
                ],
            }), encoding="utf-8")

            exit_code = plan_command(wf_file, output_format="json")
            assert exit_code == 0
            data = json.loads(capsys.readouterr().out)
            task_info = data["batches"][0]["tasks"][0]
            assert task_info["when"] == "parameters.run_step == true"
            assert task_info["trigger_rule"] == "ALL_DONE"

    def test_examples_show_conditional_branching(self, capsys):
        from forge.cli.commands import examples_command

        exit_code = examples_command(show_name="conditional_branching")
        assert exit_code == 0
        captured = capsys.readouterr().out
        assert "conditional_branching" in captured
        assert "ALL_DONE" in captured

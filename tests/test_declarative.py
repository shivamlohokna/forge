"""Unit tests for Phase 7.4 — Declarative Workflow Loader in Forge."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from forge.core.engine import Engine
from forge.core.task import ExecutionContext, Task
from forge.declarative import (
    TaskSpec,
    WorkflowSpec,
    WorkflowSpecError,
    load_declarative_workflow,
    validate_workflow_dict,
)
from forge.exceptions import MissingDependencyError
from forge.plugins import DEFAULT_ENTRY_POINT_GROUP, load_plugins
from forge.registry.task_registry import TaskRegistry, get_default_registry


# ── Test Helpers ───────────────────────────────────────────────────────────────

class DummyEntryPoint:
    def __init__(self, name: str, value: str, target_obj: Any) -> None:
        self.name = name
        self.value = value
        self.group = DEFAULT_ENTRY_POINT_GROUP
        self._target_obj = target_obj

    def load(self) -> Any:
        return self._target_obj


class CustomPluginTask(Task):
    def __init__(self, multiplier: int = 2, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.multiplier = multiplier

    def execute(self, context: ExecutionContext) -> int:
        val = context.parameters.get("input_val", 10)
        return val * self.multiplier


class SamplePlugin:
    name = "declarative_test_plugin"
    version = "1.0.0"

    def register(self, registry: TaskRegistry) -> None:
        registry.register("math_custom", CustomPluginTask)


# ── Test Cases ─────────────────────────────────────────────────────────────────

def test_workflow_spec_from_dict():
    """Verify WorkflowSpec and TaskSpec dataclass parsing."""
    raw = {
        "name": "Pipeline",
        "description": "Sample pipeline",
        "parameters": {"env": "prod"},
        "tasks": [
            {
                "id": "t1",
                "type": "shell",
                "params": {"command": "echo hello"},
                "retry_policy": {"max_retries": 3, "delay": 1.5},
            },
            {
                "id": "t2",
                "type": "file",
                "depends_on": ["t1"],
                "params": {"filepath": "out.txt", "operation": "read"},
            },
        ],
    }

    spec = WorkflowSpec.from_dict(raw)
    assert spec.name == "Pipeline"
    assert spec.description == "Sample pipeline"
    assert spec.parameters == {"env": "prod"}
    assert len(spec.tasks) == 2

    t1 = spec.tasks[0]
    assert t1.id == "t1"
    assert t1.type == "shell"
    assert t1.params == {"command": "echo hello"}
    assert t1.max_retries == 3
    assert t1.retry_delay == 1.5

    t2 = spec.tasks[1]
    assert t2.depends_on == ["t1"]


def test_valid_declarative_workflow_loading_from_dict():
    """Verify loading a valid declarative workflow from a dictionary."""
    data = {
        "name": "Shell Pipeline",
        "tasks": [
            {
                "id": "step1",
                "type": "shell",
                "params": {"command": "echo step1"},
            },
            {
                "id": "step2",
                "type": "shell",
                "depends_on": ["step1"],
                "params": {"command": "echo step2"},
            },
        ],
    }

    wf = load_declarative_workflow(data)
    assert wf.name == "Shell Pipeline"
    assert len(wf.tasks) == 2
    assert wf.has_task("step1")
    assert wf.has_task("step2")

    t1 = wf.get_task("step1")
    t2 = wf.get_task("step2")
    assert t1 in t2.dependencies


def test_valid_declarative_workflow_loading_from_json_string():
    """Verify loading a valid declarative workflow from a JSON string."""
    raw_json = json.dumps({
        "name": "JSON Workflow",
        "tasks": [
            {
                "id": "ping",
                "type": "shell",
                "params": {"command": "echo pong"},
            }
        ],
    })

    wf = load_declarative_workflow(raw_json)
    assert wf.name == "JSON Workflow"
    assert wf.has_task("ping")


@pytest.mark.parametrize(
    "invalid_data, error_match",
    [
        ("invalid json {", r"Failed to parse JSON workflow definition"),
        (12345, r"Workflow data must be a dict, str, or Path"),
        ([], r"Workflow data must be a dict, str, or Path"),


        ({}, r"Workflow 'name' is required"),
        ({"name": ""}, r"Workflow 'name' is required"),
        ({"name": "NoTasks"}, r"Workflow 'tasks' is required"),
        ({"name": "EmptyTasks", "tasks": []}, r"Workflow 'tasks' list cannot be empty"),
        ({"name": "BadTaskType", "tasks": ["not_a_dict"]}, r"tasks\[0\] must be a dictionary"),
        ({"name": "NoId", "tasks": [{"type": "shell"}]}, r"tasks\[0\]\.id is required"),
        ({"name": "NoType", "tasks": [{"id": "t1"}]}, r"tasks\[0\]\.type is required"),
        (
            {"name": "DupId", "tasks": [{"id": "t1", "type": "shell"}, {"id": "t1", "type": "shell"}]},
            r"Duplicate task id 't1'",
        ),
        (
            {"name": "UnknownType", "tasks": [{"id": "t1", "type": "nonexistent_task_type"}]},
            r"tasks\[0\]\.type: unknown task type 'nonexistent_task_type'",
        ),
        (
            {"name": "UnknownDep", "tasks": [{"id": "t1", "type": "shell", "depends_on": ["missing_dep"]}]},
            r"tasks\[0\]\.depends_on: task 't1' depends on unknown task id 'missing_dep'",
        ),
        (
            {"name": "SelfDep", "tasks": [{"id": "t1", "type": "shell", "depends_on": ["t1"]}]},
            r"task 't1' cannot depend on itself",
        ),
        (
            {"name": "BadStrategy", "tasks": [{"id": "t1", "type": "shell", "failure_strategy": "INVALID"}]},
            r"tasks\[0\]\.failure_strategy: invalid strategy",
        ),
        (
            {"name": "BadRetries", "tasks": [{"id": "t1", "type": "shell", "max_retries": -1}]},
            r"tasks\[0\]\.max_retries: must be an integer >= 0",
        ),
        (
            {"name": "BadTimeout", "tasks": [{"id": "t1", "type": "shell", "timeout": -5}]},
            r"tasks\[0\]\.timeout: must be a number > 0",
        ),
    ],
)
def test_declarative_validation_failures(invalid_data: Any, error_match: str):
    """Verify validation errors are raised with clear, context-specific error messages."""
    with pytest.raises((WorkflowSpecError, TypeError), match=error_match):
        load_declarative_workflow(invalid_data)


def test_code_execution_prevention():
    """Verify executable functions/lambdas are rejected in declarative parameters."""
    bad_dict = {
        "name": "Code Injection Attempt",
        "tasks": [
            {
                "id": "malicious",
                "type": "shell",
                "params": {
                    "command": "echo hi",
                    "fn": lambda x: x + 1,  # Lambda injected in parameters
                },
            }
        ],
    }

    with pytest.raises(WorkflowSpecError, match=r"Executable code or callable at 'workflow\.tasks\[0\]\.params\.fn' is not permitted"):
        load_declarative_workflow(bad_dict)


def test_full_chain_plugin_discovery_to_declarative_execution():
    """Verify end-to-end chain: plugin discovery -> TaskRegistry -> declarative workflow -> Engine execution."""
    registry = TaskRegistry()
    ep = DummyEntryPoint("plugin_ep", "pkg:SamplePlugin", SamplePlugin())

    # 1. Discover and load plugin into TaskRegistry
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        load_plugins(registry)

    assert "math_custom" in registry

    # 2. Define declarative workflow referencing custom plugin task type
    decl_workflow_json = json.dumps({
        "name": "Declarative Plugin Pipeline",
        "description": "Executes custom plugin task via declarative loader",
        "tasks": [
            {
                "id": "custom_multiplier",
                "type": "math_custom",
                "params": {
                    "multiplier": 4,
                },
            }
        ],
    })

    # 3. Load declarative workflow using our registry
    workflow = load_declarative_workflow(decl_workflow_json, registry=registry)
    assert workflow.name == "Declarative Plugin Pipeline"
    assert workflow.has_task("custom_multiplier")

    # 4. Execute workflow through unchanged Engine
    engine = Engine(verbose=False)
    result = engine.run(workflow, parameters={"input_val": 8})

    assert result.is_success
    assert result.get_task_result("custom_multiplier").output == 32

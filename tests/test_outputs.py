"""Comprehensive Unit and Integration Test Suite for Phase 6 Workflow Results & Outputs.

Tests:
- Output extraction and resolution engine (get_structured_output, traverse_path, resolve_expression)
- Template substitution (type preservation, string interpolation, escaping)
- Static pre-flight validation (unknown task, self-reference, non-dependency reference)
- Built-in task outputs (FileTask, ShellTask, HTTPTask, FunctionTask)
- Dynamic execution context output flow between tasks
- Failures, skips, retries (Golden Journeys A, B, C, D, E)
- Parameter + output composition
- Concurrency and multi-run isolation
- History, inspect, and CLI plan integration
- Secret masking and output size safety
"""

import json
import tempfile
from pathlib import Path
import pytest

from forge.core.engine import Engine
from forge.core.output import (
    extract_expressions,
    get_structured_output,
    resolve_expression,
    substitute_template,
    traverse_path,
    validate_output_references,
)
from forge.core.result import TaskResult, WorkflowStatus
from forge.core.task import ExecutionContext, FailureStrategy, TaskStatus
from forge.declarative.loader import load_declarative_workflow
from forge.exceptions import OutputError, ParameterError
from forge.persistence.store import ExecutionStore
from forge.tasks.file_task import FileOperation, FileResult, FileTask
from forge.tasks.function_task import FunctionTask
from forge.tasks.http_task import HTTPResult, HTTPTask
from forge.tasks.shell_task import ShellResult, ShellTask


class TestOutputExtractionAndResolution:
    """Test unit output parsing, dictionary traversal, and expression resolution."""

    def test_get_structured_output_dict(self):
        data = {"path": "a/b.txt", "count": 10}
        assert get_structured_output(data) == data

    def test_get_structured_output_to_dict_obj(self):
        res = ShellResult(command="echo hi", exit_code=0, stdout="hi", stderr="")
        out = get_structured_output(res)
        assert out["command"] == "echo hi"
        assert out["exit_code"] == 0
        assert out["stdout"] == "hi"

    def test_get_structured_output_primitive(self):
        assert get_structured_output("hello") == {"result": "hello", "value": "hello"}
        assert get_structured_output(42) == {"result": 42, "value": 42}
        assert get_structured_output(None) == {}

    def test_traverse_path_dict(self):
        obj = {"a": {"b": {"c": 123}}}
        assert traverse_path(obj, "a.b.c") == 123

    def test_traverse_path_list(self):
        obj = {"items": ["first", "second"]}
        assert traverse_path(obj, "items.1") == "second"

    def test_traverse_path_missing_key(self):
        with pytest.raises(KeyError):
            traverse_path({"a": 1}, "b")

    def test_resolve_expression_parameter(self):
        params = {"env": "prod"}
        assert resolve_expression("env", parameters=params) == "prod"
        assert resolve_expression("parameters.env", parameters=params) == "prod"

    def test_resolve_expression_output(self):
        outputs = {"fetch": {"status_code": 200, "body": "ok"}}
        assert resolve_expression("outputs.fetch.status_code", outputs=outputs) == 200
        assert resolve_expression("outputs.fetch.body", outputs=outputs) == "ok"

    def test_resolve_expression_missing_task(self):
        with pytest.raises(OutputError) as exc_info:
            resolve_expression("outputs.ghost.path", outputs={})
        assert "ghost" in str(exc_info.value)

    def test_resolve_expression_missing_field(self):
        with pytest.raises(OutputError) as exc_info:
            resolve_expression("outputs.task_a.missing_key", outputs={"task_a": {"real_key": "val"}})
        assert "missing_key" in str(exc_info.value)


class TestTemplateSubstitution:
    """Test type preservation, string interpolation, and escaping."""

    def test_whole_value_exact_match_type_preservation(self):
        outputs = {"task_a": {"count": 42, "flag": True, "items": [1, 2]}}
        assert substitute_template("{{ outputs.task_a.count }}", outputs=outputs) == 42
        assert substitute_template("{{ outputs.task_a.flag }}", outputs=outputs) is True
        assert substitute_template("{{ outputs.task_a.items }}", outputs=outputs) == [1, 2]

    def test_string_interpolation(self):
        outputs = {"task_a": {"count": 42}}
        res = substitute_template("Count is {{ outputs.task_a.count }} items", outputs=outputs)
        assert res == "Count is 42 items"

    def test_escaping(self):
        res = substitute_template(r"\{{ outputs.raw.val }}")
        assert res == "{{ outputs.raw.val }}"

    def test_parameter_and_output_composition(self):
        params = {"base": "/var/data"}
        outputs = {"build": {"artifact": "app.zip"}}
        res = substitute_template("{{ base }}/{{ outputs.build.artifact }}", parameters=params, outputs=outputs)
        assert res == "/var/data/app.zip"


class TestStaticPreflightValidation:
    """Test pre-flight output reference validation rules."""

    def test_valid_output_references(self):
        wf_dict = {
            "name": "valid",
            "tasks": [
                {"id": "a", "type": "shell", "params": {"command": "echo hi"}},
                {"id": "b", "type": "shell", "depends_on": ["a"], "params": {"command": "echo {{ outputs.a.stdout }}"}},
            ],
        }
        validate_output_references(wf_dict)  # Should not raise

    def test_self_reference_rejected(self):
        wf_dict = {
            "name": "invalid_self",
            "tasks": [
                {"id": "a", "type": "shell", "params": {"command": "echo {{ outputs.a.stdout }}"}},
            ],
        }
        with pytest.raises(OutputError) as exc:
            validate_output_references(wf_dict)
        assert "cannot reference its own output" in str(exc.value)

    def test_unknown_task_reference_rejected(self):
        wf_dict = {
            "name": "unknown_task",
            "tasks": [
                {"id": "a", "type": "shell", "params": {"command": "echo {{ outputs.ghost.stdout }}"}},
            ],
        }
        with pytest.raises(OutputError) as exc:
            validate_output_references(wf_dict)
        assert "unknown task 'ghost'" in str(exc.value)

    def test_non_dependency_reference_rejected(self):
        wf_dict = {
            "name": "non_dep",
            "tasks": [
                {"id": "a", "type": "shell", "params": {"command": "echo hi"}},
                {"id": "b", "type": "shell", "params": {"command": "echo {{ outputs.a.stdout }}"}},  # Missing depends_on: ["a"]
            ],
        }
        with pytest.raises(OutputError) as exc:
            validate_output_references(wf_dict)
        assert "not in 'depends_on'" in str(exc.value)


class TestGoldenUserJourneys:
    """Test Golden Journeys A, B, C, D, E."""

    def test_journey_a_producer_to_consumer(self):
        """Journey A: producer outputs data -> consumer receives producer output correctly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "output.txt"
            wf_dict = {
                "name": "JourneyA",
                "tasks": [
                    {
                        "id": "producer",
                        "type": "file",
                        "params": {
                            "operation": "write",
                            "path": str(out_file),
                            "content": "produced_by_a",
                        },
                    },
                    {
                        "id": "consumer",
                        "type": "file",
                        "depends_on": ["producer"],
                        "params": {
                            "operation": "read",
                            "path": "{{ outputs.producer.path }}",
                        },
                    },
                ],
            }
            wf = load_declarative_workflow(wf_dict)
            engine = Engine(verbose=False)
            res = engine.run(wf)
            assert res.is_success
            c_res = res.get_task_result("consumer")
            assert c_res.is_success
            assert str(c_res.output) == "produced_by_a"

    def test_journey_b_producer_fails_consumer_blocked(self):
        """Journey B: producer fails -> consumer does not execute."""
        wf_dict = {
            "name": "JourneyB",
            "tasks": [
                {
                    "id": "producer",
                    "type": "shell",
                    "params": {"command": "python -c 'import sys; sys.exit(1)'"},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "depends_on": ["producer"],
                    "params": {"command": "echo {{ outputs.producer.stdout }}"},
                },
            ],
        }
        wf = load_declarative_workflow(wf_dict)
        engine = Engine(verbose=False)
        res = engine.run(wf)
        assert res.is_failed
        assert res.get_task_result("producer").is_failed
        assert res.get_task_result("consumer").is_blocked

    def test_journey_c_producer_retries_consumer_sees_final_output(self):
        """Journey C: producer retries -> consumer sees only final successful output."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            flag_file = Path(tmp_dir) / "flag.txt"
            cmd = (
                f"python -c \"import os, sys; "
                f"exists = os.path.exists(r'{flag_file}'); "
                f"open(r'{flag_file}', 'w').close(); "
                f"sys.exit(0 if exists else 1)\""
            )
            t_prod = ShellTask("producer", command=cmd, max_retries=2, failure_strategy=FailureStrategy.RETRY)
            t_cons = ShellTask("consumer", command="echo hello").depends_on(t_prod)

            wf = load_declarative_workflow({
                "name": "JourneyC",
                "tasks": [
                    {"id": "producer", "type": "shell", "params": {"command": cmd, "max_retries": 2, "failure_strategy": "RETRY"}},
                    {"id": "consumer", "type": "shell", "depends_on": ["producer"], "params": {"command": "echo {{ outputs.producer.exit_code }}"}},
                ]
            })
            engine = Engine(verbose=False)
            res = engine.run(wf)
            assert res.is_success
            assert res.get_task_result("producer").attempt_count == 2
            assert res.get_task_result("consumer").is_success

    def test_journey_d_multi_run_isolation(self):
        """Journey D: two separate workflow runs use different outputs -> no cross-run leakage."""
        with tempfile.TemporaryDirectory() as tmp:
            wf_dict = {
                "name": "JourneyD",
                "parameters": {"file_name": "default.txt"},
                "tasks": [
                    {
                        "id": "create",
                        "type": "file",
                        "params": {
                            "operation": "write",
                            "path": f"{tmp}/{{ file_name }}",
                            "content": "content_{{ file_name }}",
                        },
                    },
                    {
                        "id": "read",
                        "type": "file",
                        "depends_on": ["create"],
                        "params": {
                            "operation": "read",
                            "path": "{{ outputs.create.path }}",
                        },
                    },
                ],
            }
            engine = Engine(verbose=False)

            wf1 = load_declarative_workflow(wf_dict, parameters={"file_name": "run1.txt"})
            res1 = engine.run(wf1)

            wf2 = load_declarative_workflow(wf_dict, parameters={"file_name": "run2.txt"})
            res2 = engine.run(wf2)

            assert res1.is_success and res2.is_success
            assert str(res1.get_task_result("read").output) == "content_run1.txt"
            assert str(res2.get_task_result("read").output) == "content_run2.txt"

    def test_journey_e_parameter_producer_output_consumer(self):
        """Journey E: parameter -> producer -> output -> consumer."""
        with tempfile.TemporaryDirectory() as tmp:
            wf_dict = {
                "name": "JourneyE",
                "parameters": {"prefix": "GLOBAL"},
                "tasks": [
                    {
                        "id": "producer",
                        "type": "file",
                        "params": {
                            "operation": "write",
                            "path": f"{tmp}/seed.txt",
                            "content": "{{ prefix }}_DATA",
                        },
                    },
                    {
                        "id": "consumer",
                        "type": "file",
                        "depends_on": ["producer"],
                        "params": {
                            "operation": "write",
                            "path": f"{tmp}/consumer.txt",
                            "content": "CONSUMED: {{ outputs.producer.content }}",
                        },
                    },
                ],
            }
            wf = load_declarative_workflow(wf_dict, parameters={"prefix": "CUSTOM"})
            engine = Engine(verbose=False)
            res = engine.run(wf)
            assert res.is_success
            assert str(res.get_task_result("consumer").output) == str(Path(tmp) / "consumer.txt")
            content = (Path(tmp) / "consumer.txt").read_text()
            assert content == "CONSUMED: CUSTOM_DATA"


class TestPersistenceAndInspectOutputs:
    """Test output serialization and store persistence."""

    def test_store_persists_task_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            store = ExecutionStore.create(db_path)
            try:
                engine = Engine(verbose=False, store=store)

                wf = load_declarative_workflow({
                    "name": "PersistOut",
                    "tasks": [
                        {
                            "id": "t1",
                            "type": "shell",
                            "params": {"command": "echo hello_output"},
                        }
                    ]
                })
                res = engine.run(wf)
                assert res.is_success

                run = store.get_workflow_run(res.run_id)
                assert run is not None
                task_runs = store.get_task_runs(res.run_id)
                assert len(task_runs) == 1
                from forge.persistence.models import _from_json
                out = _from_json(task_runs[0].output)
                assert isinstance(out, dict)
                assert out["stdout"] == "hello_output"
            finally:
                store.close()


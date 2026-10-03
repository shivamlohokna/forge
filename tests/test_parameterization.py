"""Tests for Phase 5 — Workflow Parameterization.

Covers:
- ParameterSpec parsing (shorthand and full dict)
- Parameter validation (required/optional/defaults)
- Unknown parameter rejection
- Type coercion (string, integer, number, boolean)
- Type mismatch errors
- Template substitution (whole-value replacement with type preservation)
- String interpolation with mixed content
- Escaped template syntax (backslash-{{ }})
- Nested dict/list traversal
- Substitution of undefined parameter (error)
- Secret parameter masking
- CLI parse_cli_parameter_args (key=value pairs, --params file)
- load_declarative_workflow with runtime parameters
- plan_command with parameters (table + JSON)
- run_command with parameters
- Golden-path journeys A/B/C/D
- Backward compatibility (no-parameter workflows unchanged)
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import pytest

from forge.declarative.parameters import (
    ParameterSpec,
    mask_secret_parameters,
    parse_parameter_specs,
    resolve_and_validate_parameters,
    substitute_parameters,
)
from forge.exceptions import LoadError, ParameterError, WorkflowSpecError
from forge.declarative import load_declarative_workflow
from forge.registry.task_registry import TaskRegistry
from forge.registry.builtins import register_builtin_tasks
from forge.cli.loader import load_workflow, parse_cli_parameter_args
from forge.cli.commands import plan_command, run_command, validate_command


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _registry() -> TaskRegistry:
    r = TaskRegistry()
    register_builtin_tasks(r)
    return r


def _make_workflow_dict(param_decl: dict | None = None, tasks: list | None = None) -> dict:
    return {
        "name": "Test",
        "parameters": param_decl or {},
        "tasks": tasks or [
            {"id": "t1", "type": "function", "params": {"fn": lambda ctx: "ok"}}
        ],
    }


# ─── ParameterSpec parsing ────────────────────────────────────────────────────

class TestParameterSpecParsing:
    def test_shorthand_string(self):
        spec = ParameterSpec.from_dict("label", "hello")
        assert spec.name == "label"
        assert spec.type == "string"
        assert spec.default == "hello"
        assert not spec.required
        assert not spec.secret

    def test_shorthand_integer(self):
        spec = ParameterSpec.from_dict("workers", 4)
        assert spec.type == "integer"
        assert spec.default == 4

    def test_shorthand_float(self):
        spec = ParameterSpec.from_dict("ratio", 0.5)
        assert spec.type == "number"
        assert spec.default == 0.5

    def test_shorthand_boolean(self):
        spec = ParameterSpec.from_dict("verbose", True)
        assert spec.type == "boolean"
        assert spec.default is True

    def test_full_spec_required(self):
        spec = ParameterSpec.from_dict("src", {"type": "string", "required": True, "description": "source dir"})
        assert spec.type == "string"
        assert spec.required is True
        assert spec.default is None
        assert spec.description == "source dir"

    def test_full_spec_with_default(self):
        spec = ParameterSpec.from_dict("keep", {"type": "integer", "default": 7})
        assert spec.type == "integer"
        assert spec.default == 7
        assert spec.required is False   # has default

    def test_full_spec_secret(self):
        spec = ParameterSpec.from_dict("token", {"type": "string", "required": True, "secret": True})
        assert spec.secret is True

    def test_invalid_type_raises(self):
        with pytest.raises(ParameterError, match="Invalid parameter type"):
            ParameterSpec.from_dict("x", {"type": "datetime"})

    def test_type_aliases(self):
        assert ParameterSpec.from_dict("a", {"type": "str"}).type == "string"
        assert ParameterSpec.from_dict("b", {"type": "int"}).type == "integer"
        assert ParameterSpec.from_dict("c", {"type": "float"}).type == "number"
        assert ParameterSpec.from_dict("d", {"type": "bool"}).type == "boolean"


class TestParseParameterSpecs:
    def test_empty_is_ok(self):
        specs = parse_parameter_specs({})
        assert specs == {}

    def test_mixed(self):
        specs = parse_parameter_specs({"src": {"type": "string", "required": True}, "n": 5})
        assert "src" in specs
        assert "n" in specs
        assert specs["n"].default == 5

    def test_non_dict_raises(self):
        with pytest.raises(ParameterError):
            parse_parameter_specs("not a dict")   # type: ignore[arg-type]


# ─── Parameter validation ─────────────────────────────────────────────────────

class TestResolveAndValidateParameters:
    def _specs(self, decl: dict) -> dict:
        return parse_parameter_specs(decl)

    def test_required_provided(self):
        specs = self._specs({"src": {"type": "string", "required": True}})
        resolved = resolve_and_validate_parameters(specs, {"src": "/data"})
        assert resolved["src"] == "/data"

    def test_required_missing_raises(self):
        specs = self._specs({"src": {"type": "string", "required": True}})
        with pytest.raises(ParameterError, match="required"):
            resolve_and_validate_parameters(specs, {})

    def test_optional_default(self):
        specs = self._specs({"n": 7})
        resolved = resolve_and_validate_parameters(specs, {})
        assert resolved["n"] == 7

    def test_user_overrides_default(self):
        specs = self._specs({"n": 7})
        resolved = resolve_and_validate_parameters(specs, {"n": 14})
        assert resolved["n"] == 14

    def test_unknown_parameter_raises(self):
        specs = self._specs({"src": {"type": "string", "required": True}})
        with pytest.raises(ParameterError, match="Unknown parameter"):
            resolve_and_validate_parameters(specs, {"src": "/x", "typo": "oops"})

    def test_no_specs_no_params_ok(self):
        resolved = resolve_and_validate_parameters({}, {})
        assert resolved == {}

    def test_no_specs_with_params_raises(self):
        with pytest.raises(ParameterError, match="Unknown parameter"):
            resolve_and_validate_parameters({}, {"x": "y"})


# ─── Type coercion ────────────────────────────────────────────────────────────

class TestTypeCoercion:
    def _resolve(self, type_str: str, val: Any) -> Any:
        specs = parse_parameter_specs({"x": {"type": type_str, "required": True}})
        return resolve_and_validate_parameters(specs, {"x": val})["x"]

    # string
    def test_string_from_string(self):
        assert self._resolve("string", "hello") == "hello"

    def test_string_from_int(self):
        assert self._resolve("string", 42) == "42"

    def test_string_from_dict_raises(self):
        with pytest.raises(ParameterError, match="Type mismatch"):
            self._resolve("string", {"a": 1})

    # integer
    def test_integer_from_int(self):
        assert self._resolve("integer", 10) == 10
        assert isinstance(self._resolve("integer", 10), int)

    def test_integer_from_str(self):
        assert self._resolve("integer", "10") == 10

    def test_integer_from_bool_raises(self):
        with pytest.raises(ParameterError, match="integer"):
            self._resolve("integer", True)

    def test_integer_from_invalid_raises(self):
        with pytest.raises(ParameterError, match="expects integer"):
            self._resolve("integer", "many")

    # number
    def test_number_from_float(self):
        assert self._resolve("number", 3.14) == pytest.approx(3.14)

    def test_number_from_int(self):
        result = self._resolve("number", 5)
        assert result == 5

    def test_number_from_str(self):
        assert self._resolve("number", "2.5") == pytest.approx(2.5)

    def test_number_from_bool_raises(self):
        with pytest.raises(ParameterError, match="number"):
            self._resolve("number", False)

    def test_number_from_invalid_raises(self):
        with pytest.raises(ParameterError, match="expects number"):
            self._resolve("number", "abc")

    # boolean
    def test_boolean_from_bool(self):
        assert self._resolve("boolean", True) is True
        assert self._resolve("boolean", False) is False

    def test_boolean_from_str_true(self):
        for s in ("true", "True", "TRUE", "yes", "1", "on"):
            assert self._resolve("boolean", s) is True

    def test_boolean_from_str_false(self):
        for s in ("false", "False", "FALSE", "no", "0", "off"):
            assert self._resolve("boolean", s) is False

    def test_boolean_from_invalid_raises(self):
        with pytest.raises(ParameterError, match="boolean"):
            self._resolve("boolean", "maybe")


# ─── Substitution ─────────────────────────────────────────────────────────────

class TestSubstituteParameters:
    def test_whole_value_string(self):
        result = substitute_parameters("{{ src }}", {"src": "/data"})
        assert result == "/data"

    def test_whole_value_integer_preserves_type(self):
        result = substitute_parameters("{{ n }}", {"n": 42})
        assert result == 42
        assert isinstance(result, int)

    def test_whole_value_boolean_preserves_type(self):
        result = substitute_parameters("{{ flag }}", {"flag": True})
        assert result is True

    def test_whole_value_float_preserves_type(self):
        result = substitute_parameters("{{ ratio }}", {"ratio": 3.14})
        assert result == pytest.approx(3.14)

    def test_string_interpolation(self):
        result = substitute_parameters("Hello {{ name }}!", {"name": "world"})
        assert result == "Hello world!"

    def test_multiple_placeholders(self):
        result = substitute_parameters("{{ a }} + {{ b }}", {"a": "X", "b": "Y"})
        assert result == "X + Y"

    def test_escaped_placeholder(self):
        result = substitute_parameters(r"\{{ kept }}", {"kept": "ignored"})
        assert result == "{{ kept }}"

    def test_dict_recursive(self):
        data = {"path": "{{ src }}/file.json", "count": "{{ n }}"}
        result = substitute_parameters(data, {"src": "/data", "n": 5})
        assert result["path"] == "/data/file.json"
        assert result["count"] == 5   # whole-value {{ n }} → type-preserved integer

    def test_list_recursive(self):
        result = substitute_parameters(["{{ a }}", "{{ b }}"], {"a": 1, "b": 2})
        assert result == [1, 2]

    def test_whole_value_in_list(self):
        result = substitute_parameters(["{{ n }}", "text"], {"n": 99})
        assert result[0] == 99
        assert isinstance(result[0], int)

    def test_nested_dict(self):
        data = {"outer": {"inner": "{{ x }}"}}
        result = substitute_parameters(data, {"x": "deep"})
        assert result["outer"]["inner"] == "deep"

    def test_undefined_placeholder_raises(self):
        with pytest.raises(ParameterError, match="not defined"):
            substitute_parameters("{{ missing }}", {})

    def test_non_string_value_passthrough(self):
        assert substitute_parameters(42, {"x": "y"}) == 42
        assert substitute_parameters(True, {}) is True
        assert substitute_parameters(None, {}) is None

    def test_keys_never_substituted(self):
        data = {"{{ key }}": "value"}
        result = substitute_parameters(data, {"key": "replaced"})
        # Key must remain unchanged
        assert "{{ key }}" in result

    def test_no_double_substitution(self):
        # Value of 'a' contains {{ b }} — that must NOT be re-expanded
        result = substitute_parameters("{{ a }}", {"a": "{{ b }}", "b": "danger"})
        assert result == "{{ b }}"

    def test_whitespace_in_placeholder(self):
        result = substitute_parameters("{{  src  }}", {"src": "/data"})
        assert result == "/data"


# ─── Secret masking ───────────────────────────────────────────────────────────

class TestMaskSecretParameters:
    def test_masks_secret(self):
        specs = parse_parameter_specs({
            "token": {"type": "string", "required": True, "secret": True},
            "label": "hello",
        })
        params = {"token": "my-secret-value", "label": "hello"}
        masked = mask_secret_parameters(params, specs)
        assert masked["token"] == "********"
        assert masked["label"] == "hello"

    def test_non_secret_unchanged(self):
        params = {"a": "x", "b": 5}
        masked = mask_secret_parameters(params, {})
        assert masked == params

    def test_original_not_mutated(self):
        specs = parse_parameter_specs({"pw": {"type": "string", "required": True, "secret": True}})
        params = {"pw": "secret"}
        masked = mask_secret_parameters(params, specs)
        assert params["pw"] == "secret"   # original unchanged
        assert masked["pw"] == "********"


# ─── load_declarative_workflow with parameters ────────────────────────────────

def _shell_task(task_id: str = "t1", command: str = "echo ok") -> dict:
    """Return a minimal safe shell task dict."""
    return {"id": task_id, "type": "shell", "params": {"command": command}}


class TestLoadDeclarativeWorkflowParameters:
    def test_load_with_required_param(self):
        wf = load_declarative_workflow(
            {"name": "W", "parameters": {"src": {"type": "string", "required": True}},
             "tasks": [_shell_task()]},
            parameters={"src": "/data"},
        )
        assert wf.parameters["src"] == "/data"

    def test_load_missing_required_param_raises(self):
        with pytest.raises((WorkflowSpecError, ParameterError, LoadError)):
            load_declarative_workflow(
                {"name": "W", "parameters": {"src": {"type": "string", "required": True}},
                 "tasks": [_shell_task()]},
                parameters=None,
            )

    def test_load_unknown_param_raises(self):
        with pytest.raises((WorkflowSpecError, ParameterError, LoadError)):
            load_declarative_workflow(
                {"name": "W", "parameters": {},
                 "tasks": [_shell_task()]},
                parameters={"unknown": "oops"},
            )

    def test_load_default_used_when_not_provided(self):
        wf = load_declarative_workflow(
            {"name": "W",
             "parameters": {"n": {"type": "integer", "default": 7}},
             "tasks": [_shell_task()]},
            parameters=None,
        )
        assert wf.parameters["n"] == 7

    def test_load_no_params_workflow_unchanged(self):
        """Workflows with no parameters block still load unchanged."""
        wf = load_declarative_workflow(
            {"name": "W", "tasks": [_shell_task()]},
        )
        assert wf is not None
        assert len(wf.tasks) == 1

    def test_type_coercion_integer_via_loader(self):
        wf = load_declarative_workflow(
            {"name": "W", "parameters": {"n": {"type": "integer", "required": True}},
             "tasks": [_shell_task()]},
            parameters={"n": "10"},
        )
        assert wf.parameters["n"] == 10
        assert isinstance(wf.parameters["n"], int)

    def test_substitution_applied_in_task_params(self):
        wf = load_declarative_workflow(
            {"name": "W",
             "parameters": {"msg": {"type": "string", "required": True}},
             "tasks": [{"id": "t1", "type": "shell", "params": {"command": "echo {{ msg }}"}}]},
            parameters={"msg": "hello"},
        )
        t = wf.get_task("t1")
        assert t is not None


# ─── CLI parse_cli_parameter_args ─────────────────────────────────────────────

class TestParseCliParameterArgs:
    def test_empty(self):
        result = parse_cli_parameter_args()
        assert result == {}

    def test_single_string(self):
        result = parse_cli_parameter_args(param_list=["src=/data"])
        assert result == {"src": "/data"}

    def test_integer_auto_parse(self):
        result = parse_cli_parameter_args(param_list=["n=42"])
        assert result["n"] == 42
        assert isinstance(result["n"], int)

    def test_float_auto_parse(self):
        result = parse_cli_parameter_args(param_list=["ratio=3.14"])
        assert result["ratio"] == pytest.approx(3.14)

    def test_boolean_true(self):
        result = parse_cli_parameter_args(param_list=["flag=true"])
        assert result["flag"] is True

    def test_boolean_false(self):
        result = parse_cli_parameter_args(param_list=["flag=false"])
        assert result["flag"] is False

    def test_multiple_params(self):
        result = parse_cli_parameter_args(param_list=["a=x", "b=5", "c=true"])
        assert result == {"a": "x", "b": 5, "c": True}

    def test_value_with_equals(self):
        result = parse_cli_parameter_args(param_list=["path=C:\\Users\\foo=bar"])
        assert result["path"] == "C:\\Users\\foo=bar"

    def test_invalid_format_raises(self):
        with pytest.raises(LoadError, match="Invalid parameter format"):
            parse_cli_parameter_args(param_list=["no-equals-sign"])

    def test_empty_key_raises(self):
        with pytest.raises(LoadError, match="empty"):
            parse_cli_parameter_args(param_list=["=value"])

    def test_params_file_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"src": "/data", "n": 5}, f)
            fname = f.name
        try:
            result = parse_cli_parameter_args(params_file=fname)
            assert result == {"src": "/data", "n": 5}
        finally:
            os.unlink(fname)

    def test_params_file_missing_raises(self):
        with pytest.raises(LoadError, match="not found"):
            parse_cli_parameter_args(params_file="/nonexistent/params.json")

    def test_param_overrides_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"n": 5}, f)
            fname = f.name
        try:
            result = parse_cli_parameter_args(param_list=["n=99"], params_file=fname)
            assert result["n"] == 99
        finally:
            os.unlink(fname)


# ─── plan_command with parameters ────────────────────────────────────────────

class TestPlanCommandWithParameters:
    def _write_wf(self, tmp_path: Path, params: dict, tasks: list) -> Path:
        wf = {"name": "TestPlan", "parameters": params, "tasks": tasks}
        p = tmp_path / "wf.json"
        p.write_text(json.dumps(wf))
        return p

    def _simple_tasks(self) -> list:
        return [{"id": "t1", "type": "shell", "params": {"command": "echo {{ label }}"}}]

    def test_plan_table_with_param(self, tmp_path, capsys):
        p = self._write_wf(
            tmp_path,
            {"label": {"type": "string", "required": True}},
            self._simple_tasks(),
        )
        rc = plan_command(str(p), parameters={"label": "hello"})
        assert rc == 0
        out = capsys.readouterr().out
        assert "Parameters" in out
        assert "label" in out

    def test_plan_json_includes_parameters(self, tmp_path, capsys):
        p = self._write_wf(
            tmp_path,
            {"label": {"type": "string", "default": "default"}},
            self._simple_tasks(),
        )
        rc = plan_command(str(p), output_format="json", parameters={"label": "world"})
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "parameters" in data
        assert data["parameters"]["label"] == "world"

    def test_plan_missing_required_param_fails(self, tmp_path):
        p = self._write_wf(
            tmp_path,
            {"src": {"type": "string", "required": True}},
            self._simple_tasks(),
        )
        rc = plan_command(str(p), parameters=None)
        assert rc in (2, 3)

    def test_plan_json_valid_true(self, tmp_path, capsys):
        p = self._write_wf(
            tmp_path,
            {"label": "default"},
            self._simple_tasks(),
        )
        rc = plan_command(str(p), output_format="json")
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["valid"] is True

    def test_plan_no_side_effects(self, tmp_path, capsys):
        """plan must not create any additional files beyond the workflow file itself."""
        p = self._write_wf(tmp_path, {"label": "x"}, self._simple_tasks())
        before = set(tmp_path.iterdir())   # snapshot AFTER writing wf file
        plan_command(str(p), parameters={"label": "x"})
        after = set(tmp_path.iterdir())
        assert after == before   # plan created no new files


# ─── Backward compatibility ───────────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_workflow_without_parameters_loads(self):
        wf = load_declarative_workflow({
            "name": "NoParams",
            "tasks": [_shell_task()],
        })
        assert wf is not None
        assert wf.parameters == {}

    def test_workflow_with_shorthand_defaults_loads(self):
        wf = load_declarative_workflow({
            "name": "Shorthand",
            "parameters": {"env": "staging", "n": 5},
            "tasks": [_shell_task()],
        })
        assert wf.parameters["env"] == "staging"
        assert wf.parameters["n"] == 5


# ─── Golden user journey A: full happy path ───────────────────────────────────

class TestJourneyA:
    """validate → plan → run → parameters in result."""

    def _make_workflow(self, tmp_path: Path) -> Path:
        wf = {
            "name": "JourneyA",
            "parameters": {
                "label": {"type": "string", "required": True},
                "count": {"type": "integer", "default": 1},
            },
            "tasks": [
                {"id": "t1", "type": "shell",
                 "params": {"command": "echo {{ label }} {{ count }}"}}
            ],
        }
        p = tmp_path / "journey_a.json"
        p.write_text(json.dumps(wf))
        return p

    def test_validate_with_params(self, tmp_path, capsys):
        p = self._make_workflow(tmp_path)
        rc = validate_command(str(p), parameters={"label": "hello"})
        assert rc == 0
        out = capsys.readouterr().out
        assert "valid" in out.lower()

    def test_plan_with_params(self, tmp_path, capsys):
        p = self._make_workflow(tmp_path)
        rc = plan_command(str(p), output_format="json", parameters={"label": "hello", "count": 3})
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["parameters"]["label"] == "hello"
        assert data["parameters"]["count"] == 3


# ─── Journey B: same workflow, different parameter sets ───────────────────────

class TestJourneyB:
    def test_two_runs_produce_different_effective_params(self, tmp_path):
        wf_dict = {
            "name": "JourneyB",
            "parameters": {"label": {"type": "string", "required": True}},
            "tasks": [{"id": "t1", "type": "shell", "params": {"command": "echo {{ label }}"}}],
        }
        p = tmp_path / "b.json"
        p.write_text(json.dumps(wf_dict))

        wf1 = load_workflow(str(p), parameters={"label": "run-A"})
        wf2 = load_workflow(str(p), parameters={"label": "run-B"})

        assert wf1.parameters["label"] == "run-A"
        assert wf2.parameters["label"] == "run-B"


# ─── Journey C: missing parameter → validation fails, no execution ────────────

class TestJourneyC:
    def test_missing_required_raises_before_execution(self, tmp_path):
        wf_dict = {
            "name": "JourneyC",
            "parameters": {"src": {"type": "string", "required": True}},
            "tasks": [{"id": "t1", "type": "shell", "params": {"command": "echo {{ src }}"}}],
        }
        p = tmp_path / "c.json"
        p.write_text(json.dumps(wf_dict))

        # load_workflow must fail cleanly without executing anything
        with pytest.raises((LoadError, ParameterError, WorkflowSpecError)):
            load_workflow(str(p), parameters=None)

    def test_plan_missing_required_param_exits_nonzero(self, tmp_path):
        wf_dict = {
            "name": "JourneyC2",
            "parameters": {"src": {"type": "string", "required": True}},
            "tasks": [{"id": "t1", "type": "shell", "params": {"command": "echo {{ src }}"}}],
        }
        p = tmp_path / "c2.json"
        p.write_text(json.dumps(wf_dict))
        rc = plan_command(str(p), parameters=None)
        assert rc != 0


# ─── Journey D: invalid type → validation fails, no execution ─────────────────

class TestJourneyD:
    def test_invalid_type_raises_before_execution(self, tmp_path):
        wf_dict = {
            "name": "JourneyD",
            "parameters": {"workers": {"type": "integer", "required": True}},
            "tasks": [{"id": "t1", "type": "shell", "params": {"command": "echo hi"}}],
        }
        p = tmp_path / "d.json"
        p.write_text(json.dumps(wf_dict))

        with pytest.raises((LoadError, ParameterError, WorkflowSpecError)):
            load_workflow(str(p), parameters={"workers": "many"})

    def test_invalid_boolean_raises(self, tmp_path):
        wf_dict = {
            "name": "JourneyD2",
            "parameters": {"enabled": {"type": "boolean", "required": True}},
            "tasks": [{"id": "t1", "type": "shell", "params": {"command": "echo hi"}}],
        }
        p = tmp_path / "d2.json"
        p.write_text(json.dumps(wf_dict))

        with pytest.raises((LoadError, ParameterError, WorkflowSpecError)):
            load_workflow(str(p), parameters={"enabled": "maybe"})


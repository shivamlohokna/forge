"""Unit tests for Phase 7.5 — YAML / TOML Workflow Formats in Forge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.commands import run_command, validate_command
from forge.cli.loader import load_workflow
from forge.core.engine import Engine
from forge.declarative import (
    WorkflowSpecError,
    load_declarative_workflow,
    parse_json,
    parse_toml,
    parse_workflow_file,
    parse_yaml,
)
from forge.declarative.parsers.yaml_parser import YAML_AVAILABLE


# ── Test Cases ─────────────────────────────────────────────────────────────────

def test_json_parser():
    """Verify parse_json parses JSON strings and handles invalid format errors."""
    content = '{"name": "JSON Workflow", "tasks": [{"id": "t1", "type": "shell"}]}'
    parsed = parse_json(content)
    assert parsed["name"] == "JSON Workflow"

    with pytest.raises(WorkflowSpecError, match="Failed to parse JSON workflow definition"):
        parse_json("{invalid json")


def test_toml_parser():
    """Verify parse_toml parses TOML strings and handles invalid format errors."""
    content = """
    name = "TOML Workflow"

    [[tasks]]
    id = "t1"
    type = "shell"
    params = { command = "echo hi" }
    """
    parsed = parse_toml(content)
    assert parsed["name"] == "TOML Workflow"
    assert len(parsed["tasks"]) == 1

    with pytest.raises(WorkflowSpecError, match="Failed to parse TOML workflow definition"):
        parse_toml("invalid toml [[]")


def test_yaml_parser_missing_dependency_error():
    """Verify parse_yaml raises clear error message when PyYAML is not installed."""
    with patch("forge.declarative.parsers.yaml_parser.YAML_AVAILABLE", False):
        with pytest.raises(
            WorkflowSpecError,
            match="YAML workflow support requires the 'pyyaml' package. Install it using 'pip install pyyaml'.",
        ):
            parse_yaml("name: Test")


def test_yaml_parser_mocked_success():
    """Verify parse_yaml parses YAML mapping cleanly when PyYAML is available."""
    sample_yaml = """
    name: YAML Workflow
    description: Sample YAML workflow
    tasks:
      - id: step1
        type: shell
        params:
          command: echo hello
    """
    mock_dict = {
        "name": "YAML Workflow",
        "description": "Sample YAML workflow",
        "tasks": [
            {"id": "step1", "type": "shell", "params": {"command": "echo hello"}}
        ],
    }

    mock_yaml_mod = MagicMock()
    mock_yaml_mod.safe_load.return_value = mock_dict

    with patch("forge.declarative.parsers.yaml_parser.YAML_AVAILABLE", True):
        with patch("forge.declarative.parsers.yaml_parser.yaml", mock_yaml_mod):
            parsed = parse_yaml(sample_yaml)
            assert parsed["name"] == "YAML Workflow"
            assert parsed["tasks"][0]["id"] == "step1"


def test_format_equivalence(tmp_path: Path):
    """Verify JSON, TOML, and YAML definitions of the same workflow produce identical DAG semantics."""
    json_path = tmp_path / "workflow.json"
    toml_path = tmp_path / "workflow.toml"
    yaml_path = tmp_path / "workflow.yaml"

    json_path.write_text(
        json.dumps(
            {
                "name": "Equivalent Workflow",
                "description": "Cross-format test",
                "tasks": [
                    {"id": "t1", "type": "shell", "params": {"command": "echo t1"}},
                    {"id": "t2", "type": "shell", "depends_on": ["t1"], "params": {"command": "echo t2"}},
                ],
            }
        ),
        encoding="utf-8",
    )

    toml_path.write_text(
        """
        name = "Equivalent Workflow"
        description = "Cross-format test"

        [[tasks]]
        id = "t1"
        type = "shell"
        params = { command = "echo t1" }

        [[tasks]]
        id = "t2"
        type = "shell"
        depends_on = ["t1"]
        params = { command = "echo t2" }
        """,
        encoding="utf-8",
    )

    mock_yaml_dict = {
        "name": "Equivalent Workflow",
        "description": "Cross-format test",
        "tasks": [
            {"id": "t1", "type": "shell", "params": {"command": "echo t1"}},
            {"id": "t2", "type": "shell", "depends_on": ["t1"], "params": {"command": "echo t2"}},
        ],
    }

    mock_yaml_mod = MagicMock()
    mock_yaml_mod.safe_load.return_value = mock_yaml_dict

    # Load JSON workflow
    wf_json = load_declarative_workflow(json_path)

    # Load TOML workflow
    wf_toml = load_declarative_workflow(toml_path)

    # Load YAML workflow (using mock for PyYAML)
    with patch("forge.declarative.parsers.yaml_parser.YAML_AVAILABLE", True):
        with patch("forge.declarative.parsers.yaml_parser.yaml", mock_yaml_mod):
            yaml_path.write_text("name: Equivalent Workflow", encoding="utf-8")
            wf_yaml = load_declarative_workflow(yaml_path)

    # Assert all three produce identical DAG semantics
    for wf in (wf_json, wf_toml, wf_yaml):
        assert wf.name == "Equivalent Workflow"
        assert len(wf.tasks) == 2
        assert wf.has_task("t1")
        assert wf.has_task("t2")

        t1 = wf.get_task("t1")
        t2 = wf.get_task("t2")
        assert t1 in t2.dependencies

    # Execute all three through unchanged Engine and assert success
    engine = Engine(verbose=False)
    assert engine.run(wf_json).is_success
    assert engine.run(wf_toml).is_success
    assert engine.run(wf_yaml).is_success


def test_cli_integration_with_declarative_formats(tmp_path: Path):
    """Verify CLI load_workflow, validate_command, and run_command with JSON and TOML files."""
    json_path = tmp_path / "cli_workflow.json"
    toml_path = tmp_path / "cli_workflow.toml"

    content_dict = {
        "name": "CLI Declarative Workflow",
        "tasks": [
            {"id": "run_echo", "type": "shell", "params": {"command": "echo cli_test"}}
        ],
    }
    json_path.write_text(json.dumps(content_dict), encoding="utf-8")

    toml_content = """
    name = "CLI Declarative Workflow"

    [[tasks]]
    id = "run_echo"
    type = "shell"
    params = { command = "echo cli_test" }
    """
    toml_path.write_text(toml_content, encoding="utf-8")

    # 1. Test CLI loader on JSON file
    wf_json = load_workflow(json_path)
    assert wf_json.name == "CLI Declarative Workflow"

    # 2. Test CLI loader on TOML file
    wf_toml = load_workflow(toml_path)
    assert wf_toml.name == "CLI Declarative Workflow"

    # 3. Test CLI validate command
    assert validate_command(json_path) == 0
    assert validate_command(toml_path) == 0

    # 4. Test CLI run command
    assert run_command(json_path, quiet=True) == 0
    assert run_command(toml_path, quiet=True) == 0

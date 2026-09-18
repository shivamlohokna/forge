"""Integration tests for Phase 7.6 — Third-Party Integration Proof (forge-github)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.commands import inspect_command, run_command, validate_command
from forge.core.engine import Engine
from forge.declarative import load_declarative_workflow
from forge.exceptions import TaskExecutionError
from forge.persistence import ExecutionStore
from forge.plugins import discover_plugins, load_plugins
from forge.registry.task_registry import TaskRegistry, get_default_registry
from forge_github import GitHubClient, GitHubConfig, GitHubCreateIssueTask, GitHubPlugin


# ── Test Helpers ───────────────────────────────────────────────────────────────

def _make_mock_http_response(status_code: int = 201, payload: dict[str, Any] | None = None) -> MagicMock:
    """Create a mock HTTP response object suitable for urllib.request.urlopen context manager."""
    data = json.dumps(payload or {
        "number": 42,
        "title": "Automated Forge Issue",
        "html_url": "https://github.com/owner/repo/issues/42",
        "state": "open",
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp


# ── Test Cases ─────────────────────────────────────────────────────────────────

def test_github_plugin_entry_point_discovery():
    """Verify discover_plugins auto-discovers forge-github entry point from installed package."""
    discovered = discover_plugins()
    entry_point_names = [ep.name for ep in discovered]
    assert "github" in entry_point_names


def test_github_plugin_registration():
    """Verify loading plugins into TaskRegistry registers task type 'github.create_issue'."""
    registry = TaskRegistry()
    report = load_plugins(registry)

    assert "github.create_issue" in registry
    assert "github.create_issue" in report.registered_task_types
    assert "github" in [p.plugin_name for p in report.loaded_plugins]


def test_declarative_json_loading_with_github_task(tmp_path: Path):
    """Verify load_declarative_workflow parses JSON referencing task type 'github.create_issue'."""
    registry = TaskRegistry()
    load_plugins(registry)

    json_file = tmp_path / "github_workflow.json"
    json_file.write_text(
        json.dumps({
            "name": "GitHub Integration Workflow",
            "description": "Demonstrates third-party task plugin declarative loading",
            "tasks": [
                {
                    "id": "create_issue_task",
                    "type": "github.create_issue",
                    "params": {
                        "repository": "owner/repo",
                        "title": "Forge Phase 7.6 Integration Test",
                        "body": "Created automatically by Forge Declarative Engine",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    workflow = load_declarative_workflow(json_file, registry=registry)
    assert workflow.name == "GitHub Integration Workflow"
    assert workflow.has_task("create_issue_task")

    task = workflow.get_task("create_issue_task")
    assert isinstance(task, GitHubCreateIssueTask)
    assert task.repository == "owner/repo"
    assert task.title == "Forge Phase 7.6 Integration Test"


def test_declarative_yaml_loading_with_mocked_pyyaml(tmp_path: Path):
    """Verify load_declarative_workflow parses YAML referencing task type 'github.create_issue' when PyYAML enabled."""
    registry = TaskRegistry()
    load_plugins(registry)

    yaml_file = tmp_path / "github_workflow.yaml"
    yaml_file.write_text("dummy yaml content", encoding="utf-8")

    mock_yaml_dict = {
        "name": "YAML GitHub Workflow",
        "tasks": [
            {
                "id": "yaml_issue_task",
                "type": "github.create_issue",
                "params": {
                    "repository": "owner/yaml-repo",
                    "title": "YAML Issue Title",
                },
            }
        ],
    }

    mock_yaml_mod = MagicMock()
    mock_yaml_mod.safe_load.return_value = mock_yaml_dict

    with patch("forge.declarative.parsers.yaml_parser.YAML_AVAILABLE", True):
        with patch("forge.declarative.parsers.yaml_parser.yaml", mock_yaml_mod):
            workflow = load_declarative_workflow(yaml_file, registry=registry)

    assert workflow.name == "YAML GitHub Workflow"
    assert workflow.has_task("yaml_issue_task")
    task = workflow.get_task("yaml_issue_task")
    assert isinstance(task, GitHubCreateIssueTask)
    assert task.repository == "owner/yaml-repo"


def test_end_to_end_github_task_execution(tmp_path: Path):
    """Verify full end-to-end chain: JSON workflow -> TaskRegistry -> Engine execution -> SQLite persistence."""
    registry = TaskRegistry()
    load_plugins(registry)

    json_file = tmp_path / "deploy_notify.json"
    json_file.write_text(
        json.dumps({
            "name": "Deployment Issue Pipeline",
            "tasks": [
                {
                    "id": "notify_github",
                    "type": "github.create_issue",
                    "params": {
                        "repository": "acme/platform",
                        "title": "Production Deployment Incident",
                        "body": "Alert triggered by Forge workflow engine",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    db_file = tmp_path / "forge_test.db"
    store = ExecutionStore.create(db_file)

    workflow = load_declarative_workflow(json_file, registry=registry)
    engine = Engine(verbose=False, store=store)

    mock_resp = _make_mock_http_response(
        status_code=201,
        payload={
            "number": 108,
            "title": "Production Deployment Incident",
            "html_url": "https://github.com/acme/platform/issues/108",
            "state": "open",
        },
    )

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = engine.run(workflow, parameters={"github_token": "ghp_mock_token_abc123"})

    assert result.is_success
    task_res = result.get_task_result("notify_github")
    assert task_res.is_success
    assert task_res.output == {
        "issue_number": 108,
        "title": "Production Deployment Incident",
        "url": "https://github.com/acme/platform/issues/108",
        "repository": "acme/platform",
        "state": "open",
    }

    # Verify SQLite persistence
    persisted_run = store.get_workflow_run(result.run_id)
    assert persisted_run is not None
    assert persisted_run.status == "SUCCESS"

    task_runs = store.get_task_runs(result.run_id)
    assert len(task_runs) == 1
    assert task_runs[0].task_name == "notify_github"
    assert task_runs[0].status == "SUCCESS"

    # Verify CLI inspect visibility
    store.close()
    assert inspect_command(result.run_id, db_path=db_file) == 0



@pytest.mark.parametrize(
    "http_code, expected_err_message",
    [
        (401, "GitHub API 401 Unauthorized"),
        (404, "GitHub API 404 Not Found"),
        (422, "GitHub API 422 Unprocessable Entity"),
    ],
)
def test_github_api_error_mapping(http_code: int, expected_err_message: str):
    """Verify HTTP API errors (401, 404, 422) map into TaskExecutionError cleanly."""
    config = GitHubConfig(token="ghp_invalid_token", api_url="https://api.github.com")
    client = GitHubClient(config=config)

    error_fp = io.BytesIO(b'{"message": "Error response"}')
    http_error = urllib.error.HTTPError(
        url="https://api.github.com/repos/owner/repo/issues",
        code=http_code,
        msg="HTTP Error",
        hdrs={},
        fp=error_fp,
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(TaskExecutionError, match=expected_err_message):
            client.create_issue("owner/repo", "Test Title")


def test_missing_token_error():
    """Verify execution fails gracefully when GITHUB_TOKEN is omitted."""
    config = GitHubConfig(token=None)
    client = GitHubClient(config=config)

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(TaskExecutionError, match="GitHub API token is required"):
            client.create_issue("owner/repo", "Title")


def test_engine_core_remains_unaware_of_github():
    """Verify forge/core/engine.py has no GitHub dependencies or task-specific branching."""
    import forge.core.engine as engine_mod

    content = open(engine_mod.__file__, encoding="utf-8").read()
    assert "github" not in content.lower()
    assert "create_issue" not in content.lower()

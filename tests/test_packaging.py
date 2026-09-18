"""Automated packaging and distribution tests for Forge (Phase 8.5)."""

from __future__ import annotations

import importlib.metadata
import sys
import tomllib
from pathlib import Path

import pytest

import forge


def test_py_typed_marker_exists():
    """Verify PEP 561 py.typed marker is present in forge package."""
    forge_dir = Path(forge.__file__).parent
    py_typed_file = forge_dir / "py.typed"
    assert py_typed_file.is_file(), f"py.typed marker missing from {forge_dir}"


def test_forge_github_py_typed_marker_exists():
    """Verify PEP 561 py.typed marker is present in forge_github package."""
    import forge_github

    github_dir = Path(forge_github.__file__).parent
    py_typed_file = github_dir / "py.typed"
    assert py_typed_file.is_file(), f"py.typed marker missing from {github_dir}"


def test_pyproject_metadata():
    """Verify pyproject.toml package metadata completeness and standards compliance."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    assert pyproject_path.is_file()

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    assert project.get("name") == "forge"
    assert project.get("version") == "0.2.0"
    assert project.get("description") == "Serious Python Workflow Automation and Execution Platform"
    assert project.get("requires-python") == ">=3.10"
    assert project.get("license") == "Apache-2.0"
    assert project.get("dependencies") == []

    # Entry point
    scripts = project.get("scripts", {})
    assert scripts.get("forge") == "forge.cli.main:main"

    # Classifiers
    classifiers = project.get("classifiers", [])
    assert "Typing :: Typed" in classifiers
    assert "Development Status :: 4 - Beta" in classifiers


def test_forge_github_pyproject_metadata():
    """Verify forge-github pyproject.toml metadata and entry point definition."""
    pyproject_path = Path(__file__).resolve().parent.parent / "forge-github" / "pyproject.toml"
    assert pyproject_path.is_file()

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    assert project.get("name") == "forge-github"
    assert project.get("version") == "0.1.0"
    assert project.get("requires-python") == ">=3.10"
    assert project.get("license") == "Apache-2.0"
    assert project.get("dependencies") == []

    entry_points = project.get("entry-points", {})
    forge_plugins = entry_points.get("forge.plugins", {})
    assert forge_plugins.get("github") == "forge_github.plugin:GitHubPlugin"


def test_version_consistency():
    """Verify version consistency across code and metadata."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    assert forge.__version__ == data["project"]["version"]


def test_no_required_runtime_dependencies():
    """Verify Forge core has 0 third-party runtime dependencies."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    assert data["project"]["dependencies"] == []

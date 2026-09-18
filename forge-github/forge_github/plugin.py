"""GitHub Plugin entry point for Forge."""

from __future__ import annotations

from forge.registry.task_registry import TaskRegistry
from forge_github.tasks import GitHubCreateIssueTask


class GitHubPlugin:
    """Forge Task Plugin exposing GitHub integration tasks."""

    name = "github"
    version = "0.1.0"
    min_forge_version = "0.2.0"

    def register(self, registry: TaskRegistry) -> None:
        """Register github.create_issue task type into TaskRegistry."""
        registry.register("github.create_issue", GitHubCreateIssueTask)

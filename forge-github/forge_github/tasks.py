"""GitHub task implementations for Forge."""

from __future__ import annotations

import os
from typing import Any

from forge.core.task import ExecutionContext, Task
from forge_github.client import GitHubClient
from forge_github.config import GitHubConfig


class GitHubCreateIssueTask(Task):
    """Forge Task that creates an issue in a GitHub repository via GitHub REST API.

    Attributes:
        repository: Target repository slug (e.g., "owner/repo").
        title: Issue title.
        body: Issue body description.
    """

    def __init__(
        self,
        name: str,
        repository: str = "",
        title: str = "",
        body: str = "",
        token: str | None = None,
        api_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        self.repository = repository
        self.title = title
        self.body = body
        self.token = token
        self.api_url = api_url

    def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute issue creation using GitHubClient.

        Args:
            context: Runtime execution context passed by Forge Engine.

        Returns:
            Dict containing issue_number, url, repository, state.
        """
        repo = self.repository or context.get_param("repository")
        title = self.title or context.get_param("title")
        body = self.body or context.get_param("body", "")
        token = self.token or context.get_param("github_token") or os.environ.get("GITHUB_TOKEN")
        api_url = self.api_url or context.get_param("github_api_url") or os.environ.get("GITHUB_API_URL", "https://api.github.com")

        config = GitHubConfig(token=token, api_url=api_url)
        client = GitHubClient(config=config)

        return client.create_issue(repository=repo, title=title, body=body)

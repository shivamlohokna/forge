"""GitHub REST API client implementation using standard library urllib."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from forge.exceptions import TaskExecutionError
from forge_github.config import GitHubConfig


class GitHubClient:
    """HTTP REST client for GitHub API using standard library urllib.request."""

    def __init__(self, config: GitHubConfig | None = None) -> None:
        self.config = config or GitHubConfig.from_env()

    def create_issue(
        self,
        repository: str,
        title: str,
        body: str = "",
    ) -> dict[str, Any]:
        """Create an issue in a target GitHub repository.

        Args:
            repository: Target repository slug (e.g. "owner/repo").
            title: Issue title.
            body: Optional issue body description.

        Returns:
            Dict containing created issue details (issue_number, url, repository, state).

        Raises:
            TaskExecutionError: On missing token, authentication error, or REST API failure.
        """
        if not self.config.token:
            raise TaskExecutionError(
                "GitHub API token is required. Set GITHUB_TOKEN environment variable."
            )

        if "/" not in repository or len(repository.split("/")) != 2:
            raise TaskExecutionError(
                f"Invalid repository format '{repository}'. Must be 'owner/repo'."
            )

        if not title or not title.strip():
            raise TaskExecutionError("Issue title cannot be empty.")

        url = f"{self.config.api_url}/repos/{repository}/issues"
        payload = json.dumps({"title": title.strip(), "body": body}).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "Forge-GitHub-Plugin/0.1.0",
        }

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "issue_number": data.get("number"),
                    "title": data.get("title"),
                    "url": data.get("html_url"),
                    "repository": repository,
                    "state": data.get("state", "open"),
                }
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise TaskExecutionError(
                    "GitHub API 401 Unauthorized: Invalid or missing GITHUB_TOKEN."
                ) from exc
            elif exc.code == 404:
                raise TaskExecutionError(
                    f"GitHub API 404 Not Found: Repository '{repository}' not found or inaccessible."
                ) from exc
            elif exc.code == 422:
                raise TaskExecutionError(
                    f"GitHub API 422 Unprocessable Entity: Validation failed for issue in '{repository}'."
                ) from exc
            else:
                raise TaskExecutionError(
                    f"GitHub API Error ({exc.code}): {exc.reason}"
                ) from exc
        except urllib.error.URLError as exc:
            raise TaskExecutionError(
                f"GitHub API network connection failed: {exc.reason}"
            ) from exc
        except Exception as exc:
            raise TaskExecutionError(f"GitHub API request failed: {exc}") from exc

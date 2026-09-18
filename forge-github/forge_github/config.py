"""Configuration handling for forge-github plugin.

Resolves GitHub credentials and settings from environment variables and Forge config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GitHubConfig:
    """Resolved settings for GitHub API client.

    Attributes:
        token: GitHub Personal Access Token or Bearer Token.
        api_url: GitHub API base URL (defaults to "https://api.github.com").
    """

    token: str | None = None
    api_url: str = "https://api.github.com"

    @classmethod
    def from_env(cls) -> GitHubConfig:
        """Construct GitHubConfig from environment variables (GITHUB_TOKEN, GITHUB_API_URL)."""
        token = os.environ.get("GITHUB_TOKEN")
        api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        return cls(token=token, api_url=api_url.rstrip("/"))

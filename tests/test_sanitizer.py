"""Tests for forge.utils.sanitizer — Phase 8.2.5.

Coverage:
    - is_sensitive_key: exact, segment, embedded, false-positive guard
    - sanitize: dict, list, tuple, primitives, None, nested, depth limit
    - Persistence boundary: sanitized output is written to DB (not raw secrets)
"""

from __future__ import annotations

import pytest

from forge.utils.sanitizer import MASK, is_sensitive_key, sanitize
from forge.persistence import ExecutionStore


# =============================================================================
# is_sensitive_key
# =============================================================================

class TestIsSensitiveKey:
    """Validates word-boundary segment matching for sensitive key detection."""

    # ── True positives ────────────────────────────────────────────────────────

    def test_exact_match_password(self) -> None:
        assert is_sensitive_key("password") is True

    def test_exact_match_token(self) -> None:
        assert is_sensitive_key("token") is True

    def test_exact_match_secret(self) -> None:
        assert is_sensitive_key("secret") is True

    def test_exact_match_api_key(self) -> None:
        assert is_sensitive_key("api_key") is True

    def test_exact_match_authorization(self) -> None:
        assert is_sensitive_key("authorization") is True

    def test_exact_match_access_token(self) -> None:
        assert is_sensitive_key("access_token") is True

    def test_leading_prefix_github_token(self) -> None:
        """Pattern as trailing segment: github_token → sensitive."""
        assert is_sensitive_key("github_token") is True

    def test_leading_prefix_api_token(self) -> None:
        assert is_sensitive_key("api_token") is True

    def test_trailing_suffix_token_value(self) -> None:
        """Pattern as leading segment: token_value → sensitive."""
        assert is_sensitive_key("token_value") is True

    def test_embedded_segment_github_api_token_value(self) -> None:
        """Pattern embedded as a middle segment: github_api_token_value → sensitive."""
        assert is_sensitive_key("github_api_token_value") is True

    def test_rotation_token_count_is_sensitive(self) -> None:
        """'token' appears as a full segment in 'rotation_token_count'."""
        assert is_sensitive_key("rotation_token_count") is True

    def test_case_insensitive_PASSWORD(self) -> None:
        assert is_sensitive_key("PASSWORD") is True

    def test_case_insensitive_Authorization(self) -> None:
        assert is_sensitive_key("Authorization") is True

    def test_case_insensitive_TOKEN(self) -> None:
        assert is_sensitive_key("TOKEN") is True

    def test_auth_key(self) -> None:
        assert is_sensitive_key("auth") is True

    # ── True negatives (false-positive guard) ─────────────────────────────────

    def test_tokenize_is_not_sensitive(self) -> None:
        """`tokenize` does not contain `token` as a complete segment."""
        assert is_sensitive_key("tokenize") is False

    def test_rotation_count_is_not_sensitive(self) -> None:
        assert is_sensitive_key("rotation_count") is False

    def test_url_is_not_sensitive(self) -> None:
        assert is_sensitive_key("url") is False

    def test_repository_is_not_sensitive(self) -> None:
        assert is_sensitive_key("repository") is False

    def test_title_is_not_sensitive(self) -> None:
        assert is_sensitive_key("title") is False

    def test_status_is_not_sensitive(self) -> None:
        assert is_sensitive_key("status") is False

    def test_count_is_not_sensitive(self) -> None:
        assert is_sensitive_key("count") is False

    def test_output_is_not_sensitive(self) -> None:
        assert is_sensitive_key("output") is False

    def test_working_directory_is_not_sensitive(self) -> None:
        assert is_sensitive_key("working_directory") is False


# =============================================================================
# sanitize
# =============================================================================

class TestSanitize:
    """Validates recursive sanitization behavior."""

    # ── Dict handling ─────────────────────────────────────────────────────────

    def test_masks_sensitive_key_value(self) -> None:
        result = sanitize({"password": "s3cr3t"})
        assert result == {"password": MASK}

    def test_preserves_non_sensitive_key(self) -> None:
        result = sanitize({"url": "https://example.com"})
        assert result == {"url": "https://example.com"}

    def test_mixed_dict(self) -> None:
        data = {
            "token": "real-token-abc",
            "url": "https://api.example.com",
            "retries": 3,
        }
        result = sanitize(data)
        assert result["token"] == MASK
        assert result["url"] == "https://api.example.com"
        assert result["retries"] == 3

    def test_nested_dict(self) -> None:
        data = {
            "headers": {
                "Authorization": "Bearer secret123",
                "Content-Type": "application/json",
            }
        }
        result = sanitize(data)
        assert result["headers"]["Authorization"] == MASK
        assert result["headers"]["Content-Type"] == "application/json"

    def test_does_not_mutate_original(self) -> None:
        original = {"token": "real"}
        sanitize(original)
        assert original["token"] == "real"  # unchanged

    def test_empty_dict(self) -> None:
        assert sanitize({}) == {}

    # ── List/tuple handling ───────────────────────────────────────────────────

    def test_list_of_dicts(self) -> None:
        data = [{"token": "abc"}, {"url": "https://x.com"}]
        result = sanitize(data)
        assert result[0]["token"] == MASK
        assert result[1]["url"] == "https://x.com"

    def test_tuple_is_returned_as_list(self) -> None:
        result = sanitize(("hello", "world"))
        assert result == ["hello", "world"]

    def test_nested_list_in_dict(self) -> None:
        data = {"items": [{"secret": "val1"}, {"name": "safe"}]}
        result = sanitize(data)
        assert result["items"][0]["secret"] == MASK
        assert result["items"][1]["name"] == "safe"

    # ── Primitive handling ────────────────────────────────────────────────────

    def test_string_passthrough(self) -> None:
        """String values are never masked based on content."""
        assert sanitize("Bearer secret123") == "Bearer secret123"

    def test_int_passthrough(self) -> None:
        assert sanitize(42) == 42

    def test_float_passthrough(self) -> None:
        assert sanitize(3.14) == 3.14

    def test_bool_passthrough(self) -> None:
        assert sanitize(True) is True

    def test_none_passthrough(self) -> None:
        assert sanitize(None) is None

    # ── Depth limit ───────────────────────────────────────────────────────────

    def test_depth_limit_does_not_raise(self) -> None:
        """Deeply nested structures hit the depth limit and return MASK without crashing."""
        # Build a 25-level deep dict
        deep: dict = {}
        node = deep
        for i in range(25):
            node["nested"] = {}
            node = node["nested"]
        node["value"] = "safe"
        # Should not raise RecursionError
        result = sanitize(deep)
        assert result is not None

    # ── Real-world API config pattern ─────────────────────────────────────────

    def test_github_config_sanitization(self) -> None:
        config = {
            "repository": "owner/repo",
            "github_token": "ghp_secret123",
            "title": "Issue title",
            "body": "Issue body",
        }
        result = sanitize(config)
        assert result["github_token"] == MASK
        assert result["repository"] == "owner/repo"
        assert result["title"] == "Issue title"
        assert result["body"] == "Issue body"

    def test_http_headers_sanitization(self) -> None:
        config = {
            "url": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer tok_abc123",
                "Accept": "application/json",
            },
        }
        result = sanitize(config)
        assert result["headers"]["Authorization"] == MASK
        assert result["headers"]["Accept"] == "application/json"
        assert result["url"] == "https://api.example.com"


# =============================================================================
# Persistence boundary: secret not written raw to DB
# =============================================================================

class TestSanitizerAtPersistenceBoundary:
    """Verifies that save_task_run() writes sanitized output to the database."""

    def test_sensitive_output_is_masked_in_db(self) -> None:
        """A task output dict with a 'token' key is stored with the value masked."""
        store = ExecutionStore.in_memory()
        store.create_workflow_run(
            run_id="sanitize-test-run",
            workflow_name="SanitizeTest",
            status="RUNNING",
        )
        store.save_task_run(
            run_id="sanitize-test-run",
            task_run_id="sanitize-task-001",
            task_name="APICallTask",
            status="SUCCESS",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration_seconds=1.0,
            attempt_count=1,
            output={"access_token": "ghp_realtoken", "status": "created"},
            error_message=None,
            error_traceback=None,
        )

        rec = store.get_task_run("sanitize-task-001")
        assert rec is not None
        import json
        stored_output = json.loads(rec.output)
        # Secret is masked in DB record
        assert stored_output["access_token"] == MASK
        # Non-sensitive field is preserved
        assert stored_output["status"] == "created"
        store.close()

    def test_non_sensitive_output_is_preserved_in_db(self) -> None:
        """A task output with no sensitive keys is stored verbatim."""
        store = ExecutionStore.in_memory()
        store.create_workflow_run(
            run_id="safe-output-run",
            workflow_name="SafeOutput",
            status="RUNNING",
        )
        store.save_task_run(
            run_id="safe-output-run",
            task_run_id="safe-task-001",
            task_name="ReadFileTask",
            status="SUCCESS",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration_seconds=0.5,
            attempt_count=1,
            output={"lines": 42, "path": "/tmp/data.txt"},
            error_message=None,
            error_traceback=None,
        )

        rec = store.get_task_run("safe-task-001")
        assert rec is not None
        import json
        stored_output = json.loads(rec.output)
        assert stored_output["lines"] == 42
        assert stored_output["path"] == "/tmp/data.txt"
        store.close()

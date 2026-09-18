"""Concrete HTTPTask implementation for Forge V2.

This module provides network I/O operations (GET, POST, PUT, PATCH, DELETE),
handling query parameters, headers, JSON payloads, authentication, and
status code validation, conforming strictly to the Forge Task contract.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..core.task import (
    ExecutionContext,
    FailureStrategy,
    RetryPolicy,
    Task,
)
from ..exceptions import TaskExecutionError, TaskTimeoutError

SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "x-api-key", "api-key", "token"}


class HTTPMethod(str, Enum):
    """Supported HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


@dataclass
class HTTPResult:
    """Structured result produced by an HTTPTask execution."""

    url: str
    method: str
    status_code: int
    headers: dict[str, str]
    body: str
    duration_seconds: float = 0.0

    @property
    def is_success(self) -> bool:
        """Return True if status code is in 200..299 range."""
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        """Parse response body as JSON."""
        return json.loads(self.body)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to a serializable dictionary."""
        return {
            "url": self.url,
            "method": self.method,
            "status_code": self.status_code,
            "headers": self.headers,
            "body": self.body,
            "duration_seconds": self.duration_seconds,
        }

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access for convenience."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"HTTPResult has no attribute '{key}'")

    def __repr__(self) -> str:
        return (
            f"<HTTPResult {self.method} '{self.url}' "
            f"status={self.status_code} duration={self.duration_seconds:.2f}s>"
        )


class HTTPTask(Task):
    """A managed task that performs HTTP network requests.

    Supports methods, query params, headers, authentication, JSON payloads,
    upstream content injection, and status code evaluation.
    """

    def __init__(
        self,
        name: str,
        url: str,
        method: HTTPMethod | str = HTTPMethod.GET,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: str | bytes | None = None,
        json_data: dict[str, Any] | list[Any] | None = None,
        from_upstream: str | None = None,
        allowed_status_codes: list[int] | set[int] | None = None,
        auth: tuple[str, str] | None = None,
        bearer_token: str | None = None,
        task_id: str | None = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        retry_policy: RetryPolicy | None = None,
        failure_strategy: FailureStrategy | str = FailureStrategy.STOP,
        timeout: float | None = None,
        description: str = "",
    ) -> None:
        super().__init__(
            name=name,
            task_id=task_id,
            max_retries=max_retries,
            retry_delay=retry_delay,
            retry_policy=retry_policy,
            failure_strategy=failure_strategy,
            timeout=timeout,
            description=description,
        )

        if not url or not url.strip():
            raise ValueError(f"HTTPTask '{self.name}' requires a non-empty 'url'.")

        self.url: str = url.strip()

        if isinstance(method, str):
            try:
                self.method: HTTPMethod = HTTPMethod(method.upper())
            except ValueError:
                valid = [m.value for m in HTTPMethod]
                raise ValueError(
                    f"Invalid HTTP method '{method}'. Must be one of: {valid}"
                )
        else:
            self.method = method

        self.params: dict[str, Any] = params or {}
        self.headers: dict[str, str] = {k.lower(): v for k, v in (headers or {}).items()}
        self.data: str | bytes | None = data
        self.json_data: dict[str, Any] | list[Any] | None = json_data
        self.from_upstream: str | None = from_upstream
        self.auth: tuple[str, str] | None = auth
        self.bearer_token: str | None = bearer_token

        # Default allowed status codes: 200..299
        self.allowed_status_codes: set[int] | None = (
            set(allowed_status_codes) if allowed_status_codes is not None else None
        )

    def execute(self, context: ExecutionContext) -> HTTPResult:
        """Execute the HTTP request and evaluate the response."""
        full_url = self._build_url()
        req_headers = dict(self.headers)
        payload_bytes = self._prepare_payload(context, req_headers)

        # Apply authentication
        if self.auth:
            user, pwd = self.auth
            auth_str = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            req_headers["authorization"] = f"Basic {auth_str}"
        elif self.bearer_token:
            req_headers["authorization"] = f"Bearer {self.bearer_token}"

        # Build urllib request
        req = urllib.request.Request(
            url=full_url,
            data=payload_bytes,
            headers=req_headers,
            method=self.method.value,
        )

        start_time = time.perf_counter()

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status_code = resp.status
                resp_headers = dict(resp.headers)
                raw_body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as http_err:
            status_code = http_err.code
            resp_headers = dict(http_err.headers)
            raw_body = http_err.read().decode("utf-8", errors="replace")
            http_err.close()

        except urllib.error.URLError as url_err:
            if isinstance(url_err.reason, TimeoutError) or "timed out" in str(url_err.reason).lower():
                raise TaskTimeoutError(
                    f"HTTP {self.method.value} '{full_url}' timed out after {self.timeout:.2f}s."
                )
            raise TaskExecutionError(
                f"HTTP {self.method.value} '{full_url}' network error: {url_err.reason}"
            )
        except TimeoutError:
            raise TaskTimeoutError(
                f"HTTP {self.method.value} '{full_url}' timed out after {self.timeout:.2f}s."
            )

        duration = time.perf_counter() - start_time

        # Sanitize headers for telemetry/persistence
        sanitized_headers = {
            k: ("***" if k.lower() in SENSITIVE_HEADERS else v)
            for k, v in resp_headers.items()
        }

        http_result = HTTPResult(
            url=full_url,
            method=self.method.value,
            status_code=status_code,
            headers=sanitized_headers,
            body=raw_body,
            duration_seconds=duration,
        )

        # Evaluate allowed status codes
        if self.allowed_status_codes is not None:
            is_allowed = status_code in self.allowed_status_codes
        else:
            is_allowed = 200 <= status_code < 300

        if not is_allowed:
            allowed_repr = (
                sorted(self.allowed_status_codes)
                if self.allowed_status_codes
                else "200..299"
            )
            preview = raw_body[:200] + "..." if len(raw_body) > 200 else raw_body
            raise TaskExecutionError(
                f"HTTP {self.method.value} '{full_url}' failed with status {status_code} "
                f"(allowed: {allowed_repr}).\nResponse body: {preview or '<empty>'}"
            )

        return http_result

    def _build_url(self) -> str:
        """Append query parameters to URL if present."""
        if not self.params:
            return self.url

        url_parts = list(urllib.parse.urlparse(self.url))
        existing_params = dict(urllib.parse.parse_qsl(url_parts[4]))
        merged_params = {**existing_params, **self.params}
        url_parts[4] = urllib.parse.urlencode(merged_params)
        return urllib.parse.urlunparse(url_parts)

    def _prepare_payload(
        self,
        context: ExecutionContext,
        headers: dict[str, str],
    ) -> bytes | None:
        """Resolve body from direct arguments or upstream task output."""
        raw_payload = None

        if self.json_data is not None:
            raw_payload = self.json_data
            if "content-type" not in headers:
                headers["content-type"] = "application/json"
        elif self.data is not None:
            raw_payload = self.data
        elif self.from_upstream:
            raw_payload = context.get_upstream_result(self.from_upstream)
        elif len(self.dependencies) == 1 and self.method in (
            HTTPMethod.POST,
            HTTPMethod.PUT,
            HTTPMethod.PATCH,
        ):
            dep = next(iter(self.dependencies))
            raw_payload = context.get_upstream_result(dep.task_id)
            if raw_payload is None:
                raw_payload = context.get_upstream_result(dep.name)

        if raw_payload is None:
            return None

        # Convert payload to bytes
        if isinstance(raw_payload, (dict, list)):
            if "content-type" not in headers:
                headers["content-type"] = "application/json"
            return json.dumps(raw_payload).encode("utf-8")
        elif isinstance(raw_payload, str):
            return raw_payload.encode("utf-8")
        elif isinstance(raw_payload, bytes):
            return raw_payload
        else:
            return str(raw_payload).encode("utf-8")

    def __repr__(self) -> str:
        return (
            f"<HTTPTask id='{self.task_id}' name='{self.name}' "
            f"method='{self.method.value}' url='{self.url}' status='{self.status.value}'>"
        )

"""Concrete ShellTask implementation for Forge V2.

This module provides operating system command execution, capturing stdout,
stderr, and exit codes, and managing subprocess lifecycles while strictly
conforming to the Forge Task contract.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.task import (
    ExecutionContext,
    FailureStrategy,
    RetryPolicy,
    Task,
)
from ..exceptions import TaskExecutionError, TaskTimeoutError


@dataclass
class ShellResult:
    """Structured result produced by a ShellTask execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = 0.0

    @property
    def is_success(self) -> bool:
        """Return True if command finished with exit code 0."""
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert shell result to a serializable dictionary."""
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
        }

    def __getitem__(self, item: str) -> Any:
        """Allow dictionary-like access for convenience (e.g. res['stdout'])."""
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(f"ShellResult has no attribute '{item}'")

    def __repr__(self) -> str:
        return (
            f"<ShellResult exit_code={self.exit_code} "
            f"stdout_len={len(self.stdout)} duration={self.duration_seconds:.2f}s>"
        )


class ShellTask(Task):
    """A managed task that executes an external shell command or script.

    Captures stdout, stderr, and exit codes, handles working directories,
    environment variables, stdin piping, and enforces allowed exit codes.
    """

    def __init__(
        self,
        name: str,
        command: str | list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        stdin: str | bytes | None = None,
        from_upstream: str | None = None,
        allowed_exit_codes: list[int] | set[int] | None = None,
        shell: bool | None = None,
        encoding: str = "utf-8",
        strip_output: bool = True,
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

        if not command:
            raise ValueError(f"ShellTask '{self.name}' requires a non-empty 'command'.")

        self.command: str | list[str] = command
        self.cwd: Path | None = Path(cwd) if cwd else None
        self.env: dict[str, str] = env or {}
        self.stdin: str | bytes | None = stdin
        self.from_upstream: str | None = from_upstream
        self.allowed_exit_codes: set[int] = (
            set(allowed_exit_codes) if allowed_exit_codes is not None else {0}
        )
        # Default shell=True if string, False if list
        self.shell: bool = shell if shell is not None else isinstance(command, str)
        self.encoding: str = encoding
        self.strip_output: bool = strip_output

    def execute(self, context: ExecutionContext) -> ShellResult:
        """Execute the command as a managed subprocess."""
        if self.cwd and not self.cwd.exists():
            raise FileNotFoundError(
                f"Configured working directory does not exist: {self.cwd}"
            )

        # 1. Prepare environment: system env + user env + Forge context variables
        process_env = {**os.environ, **self.env}
        process_env["FORGE_TASK_ID"] = context.task_id
        process_env["FORGE_TASK_NAME"] = context.task_name
        if context.workflow_id:
            process_env["FORGE_WORKFLOW_ID"] = context.workflow_id
        if context.workflow_name:
            process_env["FORGE_WORKFLOW_NAME"] = context.workflow_name
        process_env["FORGE_ATTEMPT"] = str(context.attempt)

        # 2. Resolve stdin input (explicit or from upstream task)
        input_data = self._resolve_stdin(context)

        # 3. Format command representation
        cmd_str = self.command if isinstance(self.command, str) else " ".join(self.command)

        # 4. Launch subprocess
        start_time = time.perf_counter()
        proc = subprocess.Popen(
            self.command,
            cwd=str(self.cwd) if self.cwd else None,
            env=process_env,
            stdin=subprocess.PIPE if input_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=self.shell,
            text=True,
            encoding=self.encoding,
        )

        try:
            stdout_text, stderr_text = proc.communicate(
                input=input_data,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            # Kill process tree immediately on timeout
            proc.kill()
            proc.communicate()  # Drain remaining pipes
            raise TaskTimeoutError(
                f"Command '{cmd_str}' timed out after {self.timeout:.2f}s."
            )

        duration = time.perf_counter() - start_time
        exit_code = proc.returncode

        if self.strip_output:
            stdout_text = stdout_text.strip()
            stderr_text = stderr_text.strip()

        shell_result = ShellResult(
            command=cmd_str,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_seconds=duration,
        )

        # 5. Evaluate exit code success
        if exit_code not in self.allowed_exit_codes:
            err_msg = (
                f"Command '{cmd_str}' exited with code {exit_code} "
                f"(allowed: {sorted(self.allowed_exit_codes)}).\n"
                f"Stderr: {stderr_text if stderr_text else '<empty>'}\n"
                f"Stdout: {stdout_text if stdout_text else '<empty>'}"
            )
            raise TaskExecutionError(err_msg)

        return shell_result

    def _resolve_stdin(self, context: ExecutionContext) -> str | None:
        """Resolve input stream data from parameter or upstream task output."""
        if self.stdin is not None:
            raw = self.stdin
        elif self.from_upstream:
            raw = context.get_upstream_result(self.from_upstream)
        elif len(self.dependencies) == 1:
            dep = next(iter(self.dependencies))
            raw = context.get_upstream_result(dep.task_id)
            if raw is None:
                raw = context.get_upstream_result(dep.name)
        else:
            raw = None

        if raw is None:
            return None

        if isinstance(raw, bytes):
            return raw.decode(self.encoding)
        return str(raw)

    def __repr__(self) -> str:
        cmd_preview = (
            self.command[:30] + "..."
            if isinstance(self.command, str) and len(self.command) > 30
            else str(self.command)
        )
        return (
            f"<ShellTask id='{self.task_id}' name='{self.name}' "
            f"cmd='{cmd_preview}' status='{self.status.value}'>"
        )

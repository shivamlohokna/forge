"""Concrete FileTask implementation for Forge V2.

This module provides filesystem operations (read, write, append, copy, move,
delete, exists) conforming strictly to the Forge Task contract.
"""

from __future__ import annotations

import json
import os
import shutil
from enum import Enum
from pathlib import Path
from typing import Any

from ..core.task import (
    ExecutionContext,
    FailureStrategy,
    RetryPolicy,
    Task,
)


class FileOperation(str, Enum):
    """Supported filesystem operations for FileTask."""

    READ = "READ"
    WRITE = "WRITE"
    APPEND = "APPEND"
    COPY = "COPY"
    MOVE = "MOVE"
    DELETE = "DELETE"
    EXISTS = "EXISTS"


class FileTask(Task):
    """A managed task that performs filesystem operations.

    Satisfies the Forge Task contract while providing safe, validated
    filesystem interactions including dynamic upstream content injection
    and atomic file writes.
    """

    def __init__(
        self,
        name: str,
        operation: FileOperation | str,
        path: str | Path | None = None,
        source: str | Path | None = None,
        destination: str | Path | None = None,
        content: str | bytes | None = None,
        from_upstream: str | None = None,
        encoding: str = "utf-8",
        binary: bool = False,
        create_dirs: bool = True,
        missing_ok: bool = False,
        overwrite: bool = True,
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

        # Normalize operation
        if isinstance(operation, str):
            try:
                self.operation: FileOperation = FileOperation(operation.upper())
            except ValueError:
                valid = [op.value.lower() for op in FileOperation]
                raise ValueError(
                    f"Invalid file operation '{operation}'. Must be one of: {valid}"
                )
        else:
            self.operation = operation

        # Resolve path convenience shortcuts
        src = source or (path if self.operation in (
            FileOperation.READ,
            FileOperation.DELETE,
            FileOperation.EXISTS,
        ) else None)

        dest = destination or (path if self.operation in (
            FileOperation.WRITE,
            FileOperation.APPEND,
        ) else None)

        self.source: Path | None = Path(src) if src is not None else None
        self.destination: Path | None = Path(dest) if dest is not None else None
        self.content: str | bytes | None = content
        self.from_upstream: str | None = from_upstream
        self.encoding: str = encoding
        self.binary: bool = binary
        self.create_dirs: bool = create_dirs
        self.missing_ok: bool = missing_ok
        self.overwrite: bool = overwrite

        # Validate configuration upfront
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Enforce strict contract rules per operation before execution."""
        op = self.operation

        if op == FileOperation.READ:
            if not self.source:
                raise ValueError(f"FileTask '{self.name}' (READ) requires 'source' or 'path'.")
            if self.destination:
                raise ValueError(f"FileTask '{self.name}' (READ) cannot declare 'destination'.")

        elif op in (FileOperation.WRITE, FileOperation.APPEND):
            if not self.destination:
                raise ValueError(
                    f"FileTask '{self.name}' ({op.value}) requires 'destination' or 'path'."
                )
            if self.content is None and not self.from_upstream:
                # Upstream content might be bound later via dependencies; allow if dependencies exist
                pass

        elif op in (FileOperation.COPY, FileOperation.MOVE):
            if not self.source:
                raise ValueError(f"FileTask '{self.name}' ({op.value}) requires 'source'.")
            if not self.destination:
                raise ValueError(f"FileTask '{self.name}' ({op.value}) requires 'destination'.")

        elif op == FileOperation.DELETE:
            if not self.source:
                raise ValueError(f"FileTask '{self.name}' (DELETE) requires 'source' or 'path'.")

        elif op == FileOperation.EXISTS:
            if not self.source:
                raise ValueError(f"FileTask '{self.name}' (EXISTS) requires 'source' or 'path'.")

    def execute(self, context: ExecutionContext) -> Any:
        """Execute the configured filesystem operation."""
        op = self.operation

        if op == FileOperation.READ:
            return self._execute_read()

        elif op == FileOperation.WRITE:
            return self._execute_write(context)

        elif op == FileOperation.APPEND:
            return self._execute_append(context)

        elif op == FileOperation.COPY:
            return self._execute_copy()

        elif op == FileOperation.MOVE:
            return self._execute_move()

        elif op == FileOperation.DELETE:
            return self._execute_delete()

        elif op == FileOperation.EXISTS:
            return self._execute_exists()

        raise NotImplementedError(f"Unsupported file operation: {op}")

    def _execute_read(self) -> str | bytes:
        assert self.source is not None
        if not self.source.exists():
            raise FileNotFoundError(f"File not found: {self.source}")
        if self.source.is_dir():
            raise IsADirectoryError(f"Expected file but found directory: {self.source}")

        if self.binary:
            return self.source.read_bytes()
        return self.source.read_text(encoding=self.encoding)

    def _execute_write(self, context: ExecutionContext) -> str:
        assert self.destination is not None
        payload = self._resolve_payload(context)

        if self.destination.exists() and not self.overwrite:
            raise FileExistsError(
                f"Destination already exists and overwrite is False: {self.destination}"
            )

        if self.create_dirs:
            self.destination.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via temporary file
        temp_file = self.destination.with_suffix(f"{self.destination.suffix}.tmp.{os.getpid()}")
        try:
            if self.binary:
                temp_file.write_bytes(payload if isinstance(payload, bytes) else payload.encode(self.encoding))
            else:
                temp_file.write_text(payload, encoding=self.encoding)

            temp_file.replace(self.destination)
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

        return str(self.destination.resolve())

    def _execute_append(self, context: ExecutionContext) -> str:
        assert self.destination is not None
        payload = self._resolve_payload(context)

        if self.create_dirs:
            self.destination.parent.mkdir(parents=True, exist_ok=True)

        mode = "ab" if self.binary else "a"
        with open(self.destination, mode=mode, encoding=None if self.binary else self.encoding) as f:
            if self.binary:
                f.write(payload if isinstance(payload, bytes) else payload.encode(self.encoding))
            else:
                f.write(payload)

        return str(self.destination.resolve())

    def _execute_copy(self) -> str:
        assert self.source is not None and self.destination is not None
        if not self.source.exists():
            raise FileNotFoundError(f"Source does not exist: {self.source}")

        if self.destination.exists() and not self.overwrite:
            raise FileExistsError(
                f"Destination already exists and overwrite is False: {self.destination}"
            )

        if self.create_dirs:
            dest_dir = self.destination.parent if not self.source.is_dir() else self.destination
            dest_dir.mkdir(parents=True, exist_ok=True)

        if self.source.is_dir():
            shutil.copytree(self.source, self.destination, dirs_exist_ok=self.overwrite)
        else:
            shutil.copy2(self.source, self.destination)

        return str(self.destination.resolve())

    def _execute_move(self) -> str:
        assert self.source is not None and self.destination is not None
        if not self.source.exists():
            raise FileNotFoundError(f"Source does not exist: {self.source}")

        if self.destination.exists() and not self.overwrite:
            raise FileExistsError(
                f"Destination already exists and overwrite is False: {self.destination}"
            )

        if self.create_dirs:
            dest_dir = self.destination.parent if not self.source.is_dir() else self.destination
            dest_dir.mkdir(parents=True, exist_ok=True)

        shutil.move(str(self.source), str(self.destination))
        return str(self.destination.resolve())

    def _execute_delete(self) -> bool:
        assert self.source is not None
        if not self.source.exists():
            if self.missing_ok:
                return False
            raise FileNotFoundError(f"File or directory not found to delete: {self.source}")

        if self.source.is_dir():
            shutil.rmtree(self.source)
        else:
            self.source.unlink()

        return True

    def _execute_exists(self) -> bool:
        assert self.source is not None
        return self.source.exists()

    def _resolve_payload(self, context: ExecutionContext) -> str | bytes:
        """Resolve write/append content from explicit argument or upstream task output."""
        if self.content is not None:
            raw = self.content
        elif self.from_upstream:
            raw = context.get_upstream_result(self.from_upstream)
            if raw is None:
                raise ValueError(
                    f"FileTask '{self.name}' could not find output from upstream task "
                    f"'{self.from_upstream}'."
                )
        elif len(self.dependencies) == 1:
            dep = next(iter(self.dependencies))
            raw = context.get_upstream_result(dep.task_id)
            if raw is None:
                raw = context.get_upstream_result(dep.name)
            if raw is None:
                raise ValueError(
                    f"FileTask '{self.name}' has dependency '{dep.name}' but received no output."
                )
        else:
            raise ValueError(
                f"FileTask '{self.name}' ({self.operation.value}) requires content or an upstream dependency."
            )

        # If upstream output was a ShellResult or subprocess result, extract stdout
        if hasattr(raw, "stdout") and isinstance(raw.stdout, (str, bytes)):
            raw = raw.stdout

        # Format payload into str or bytes
        if self.binary:

            if isinstance(raw, bytes):
                return raw
            elif isinstance(raw, str):
                return raw.encode(self.encoding)
            else:
                return str(raw).encode(self.encoding)

        # Text mode
        if isinstance(raw, (dict, list)):
            return json.dumps(raw, indent=2)
        elif isinstance(raw, bytes):
            return raw.decode(self.encoding)
        return str(raw)

    def __repr__(self) -> str:
        target = self.destination or self.source or "unknown"
        return (
            f"<FileTask id='{self.task_id}' name='{self.name}' "
            f"op='{self.operation.value}' target='{target}' status='{self.status.value}'>"
        )

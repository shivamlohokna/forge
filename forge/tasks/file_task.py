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


from dataclasses import dataclass

@dataclass
class FileResult:
    """Structured result produced by a FileTask execution."""

    operation: str
    path: str | None = None
    content: str | bytes | None = None
    exists: bool | None = None
    size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert FileResult to a serializable dictionary for task outputs."""
        res: dict[str, Any] = {"operation": self.operation}
        if self.path is not None:
            res["path"] = self.path
        if self.content is not None:
            if isinstance(self.content, str):
                res["content"] = self.content
                res["body"] = self.content
            elif isinstance(self.content, bytes):
                try:
                    res["content"] = self.content.decode("utf-8")
                except UnicodeDecodeError:
                    res["content"] = f"<binary bytes: {len(self.content)}>"
            else:
                res["content"] = str(self.content)
        if self.exists is not None:
            res["exists"] = self.exists
        if self.size is not None:
            res["size"] = self.size
        return res

    def __str__(self) -> str:
        # For write-like operations the produced artifact is the path.
        # For read operations the produced value is the content.
        write_ops = {"WRITE", "APPEND", "COPY", "MOVE"}
        if self.operation.upper() in write_ops:
            if self.path is not None:
                return self.path
        if self.content is not None:
            return str(self.content)
        if self.path is not None:
            return self.path
        if self.exists is not None:
            return str(self.exists)
        return ""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FileResult):
            return self.to_dict() == other.to_dict()
        if isinstance(other, str):
            return str(self) == other
        if isinstance(other, bool):
            return self.exists == other if self.exists is not None else False
        if isinstance(other, (bytes, bytearray)):
            if isinstance(self.content, (bytes, bytearray)):
                return self.content == other
            return False
        return False

    def __bool__(self) -> bool:
        # EXISTS results: use the actual exists value.
        if self.operation.upper() == "EXISTS" and self.exists is not None:
            return self.exists
        # DELETE results with exists=False indicate the file is gone — falsy.
        if self.operation.upper() == "DELETE" and self.exists is False:
            return False
        # All other operations (READ, WRITE, APPEND, COPY, MOVE) are truthy
        # when they have a path or content.
        return self.path is not None or self.content is not None


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
        op_str = self.operation.value if isinstance(self.operation, FileOperation) else str(self.operation).upper()
        try:
            op = FileOperation(op_str)
        except ValueError:
            valid = [o.value for o in FileOperation]
            raise ValueError(f"Invalid file operation '{self.operation}'. Must be one of: {valid}")

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


    def _execute_read(self) -> FileResult:
        assert self.source is not None
        if not self.source.exists():
            raise FileNotFoundError(f"File not found: {self.source}")
        if self.source.is_dir():
            raise IsADirectoryError(f"Expected file but found directory: {self.source}")

        if self.binary:
            content = self.source.read_bytes()
        else:
            content = self.source.read_text(encoding=self.encoding)
        
        size = self.source.stat().st_size if self.source.exists() else None
        return FileResult(operation="READ", path=str(self.source.resolve()), content=content, size=size)

    def _execute_write(self, context: ExecutionContext) -> FileResult:
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

        resolved_path = str(self.destination.resolve())
        size = self.destination.stat().st_size if self.destination.exists() else None
        return FileResult(operation="WRITE", path=resolved_path, content=payload, size=size)

    def _execute_append(self, context: ExecutionContext) -> FileResult:
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

        resolved_path = str(self.destination.resolve())
        size = self.destination.stat().st_size if self.destination.exists() else None
        return FileResult(operation="APPEND", path=resolved_path, content=payload, size=size)


    def _execute_copy(self) -> FileResult:
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

        resolved_path = str(self.destination.resolve())
        size = self.destination.stat().st_size if self.destination.exists() else None
        return FileResult(operation="COPY", path=resolved_path, size=size)

    def _execute_move(self) -> FileResult:
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
        resolved_path = str(self.destination.resolve())
        size = self.destination.stat().st_size if self.destination.exists() else None
        return FileResult(operation="MOVE", path=resolved_path, size=size)

    def _execute_delete(self) -> FileResult:
        assert self.source is not None
        src_path = str(self.source.resolve())
        if not self.source.exists():
            if self.missing_ok:
                return FileResult(operation="DELETE", path=src_path, exists=False)
            raise FileNotFoundError(f"File or directory not found to delete: {self.source}")

        if self.source.is_dir():
            shutil.rmtree(self.source)
        else:
            self.source.unlink()

        return FileResult(operation="DELETE", path=src_path, exists=False)

    def _execute_exists(self) -> FileResult:
        assert self.source is not None
        exists_val = self.source.exists()
        src_path = str(self.source.resolve())
        size = self.source.stat().st_size if exists_val else None
        return FileResult(operation="EXISTS", path=src_path, exists=exists_val, size=size)


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

"""Structured and text logging subsystem for Forge.

Provides:
- Standard library logging integration with ForgeConfig.
- Console logging routed to ``sys.stderr`` (leaving stdout uncontaminated).
- Optional structured JSON logging (NDJSON) with ISO-8601 timestamps.
- Optional file logging with automated parent directory creation.
- Centralized secret masking to prevent credential leakage in logs.
"""

from __future__ import annotations

import datetime
import json
import logging
import sys
from pathlib import Path
from typing import Any

from forge.utils.sanitizer import sanitize

# Standard stdlib logging level mappings
_LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# Standard standard library LogRecord attributes to ignore when extracting extra fields for JSON
_STANDARD_RECORD_ATTRS: frozenset[str] = frozenset({
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "taskName",
})


class ForgeTextFormatter(logging.Formatter):
    """Text log formatter with timestamp, level, logger name, and secret masking."""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None) -> None:
        default_fmt = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
        default_datefmt = "%Y-%m-%d %H:%M:%S"
        super().__init__(fmt=fmt or default_fmt, datefmt=datefmt or default_datefmt)

    def format(self, record: logging.LogRecord) -> str:
        # Sanitize record arguments if they contain dicts/structures
        if isinstance(record.args, dict):
            record.args = sanitize(record.args)
        elif isinstance(record.args, (list, tuple)):
            record.args = tuple(sanitize(list(record.args)))
        return super().format(record)


class ForgeJsonFormatter(logging.Formatter):
    """Structured JSON formatter producing single-line NDJSON records with secret sanitization."""

    def format(self, record: logging.LogRecord) -> str:
        # Sanitize args before rendering message
        if isinstance(record.args, dict):
            record.args = sanitize(record.args)
        elif isinstance(record.args, (list, tuple)):
            record.args = tuple(sanitize(list(record.args)))

        message = record.getMessage()

        # Build timestamp in UTC ISO-8601 format
        dt = datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
        timestamp_str = dt.isoformat()

        payload: dict[str, Any] = {
            "timestamp": timestamp_str,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        # Include formatted exception information if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exception"] = record.exc_text

        # Include custom extra fields if passed via extra={...}
        raw_extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_"):
                raw_extras[key] = value
        if raw_extras:
            payload["extra"] = sanitize(raw_extras)

        return json.dumps(payload, default=str)


def get_formatter(log_format: str = "text") -> logging.Formatter:
    """Return the logging Formatter for the given format name (``'text'`` or ``'json'``)."""
    fmt = log_format.lower().strip()
    if fmt == "json":
        return ForgeJsonFormatter()
    return ForgeTextFormatter()


def setup_logging(
    config: Any = None,
    *,
    log_level: str | None = None,
    log_format: str | None = None,
    log_file: str | Path | None = None,
    stream: Any = None,
) -> logging.Logger:
    """Configure Forge logging subsystem on the ``'forge'`` parent logger.

    Args:
        config: Optional ``ForgeConfig`` instance to source defaults from.
        log_level: Optional log level string override (e.g. ``"DEBUG"``, ``"INFO"``).
        log_format: Optional log format override (``"text"`` or ``"json"``).
        log_file: Optional log file path destination.
        stream: Stream for console output. Defaults to ``sys.stderr``.

    Returns:
        The configured root ``'forge'`` logger.
    """
    resolved_level_str = "INFO"
    resolved_format_str = "text"
    resolved_file_path: str | Path | None = None

    if config is not None:
        if getattr(config, "log_level", None):
            resolved_level_str = config.log_level
        if getattr(config, "log_format", None):
            resolved_format_str = config.log_format
        if getattr(config, "log_file", None):
            resolved_file_path = config.log_file

    if log_level is not None:
        resolved_level_str = log_level
    if log_format is not None:
        resolved_format_str = log_format
    if log_file is not None:
        resolved_file_path = log_file

    level_num = _LOG_LEVELS.get(resolved_level_str.upper(), logging.INFO)
    formatter = get_formatter(resolved_format_str)

    forge_logger = logging.getLogger("forge")
    forge_logger.setLevel(level_num)

    # Remove existing handlers on the forge logger to avoid duplicate log lines
    for h in list(forge_logger.handlers):
        forge_logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    # Ensure forge_logger doesn't duplicate to root handlers if root is configured
    forge_logger.propagate = False

    # Console StreamHandler -> sys.stderr by default
    console_stream = stream if stream is not None else sys.stderr
    console_handler = logging.StreamHandler(console_stream)
    console_handler.setLevel(level_num)
    console_handler.setFormatter(formatter)
    forge_logger.addHandler(console_handler)

    # Optional FileHandler
    if resolved_file_path:
        file_path = Path(resolved_file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(level_num)
        file_handler.setFormatter(formatter)
        forge_logger.addHandler(file_handler)

    return forge_logger

"""Tests for Forge structured and text logging subsystem."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
import pytest

from forge.config import ForgeConfig
from forge.logging import (
    ForgeJsonFormatter,
    ForgeTextFormatter,
    get_formatter,
    setup_logging,
)


class TestFormatters:
    def test_text_formatter_default_format(self):
        formatter = ForgeTextFormatter()
        record = logging.LogRecord(
            name="forge.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "[INFO]" in formatted
        assert "[forge.test]" in formatted
        assert "Hello world" in formatted

    def test_text_formatter_sanitizes_dict_args(self):
        formatter = ForgeTextFormatter()
        record = logging.LogRecord(
            name="forge.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Payload: %s",
            args=({"password": "supersecret", "host": "127.0.0.1"},),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "supersecret" not in formatted
        assert "***" in formatted
        assert "127.0.0.1" in formatted

    def test_json_formatter_valid_ndjson(self):
        formatter = ForgeJsonFormatter()
        record = logging.LogRecord(
            name="forge.engine",
            level=logging.WARNING,
            pathname=__file__,
            lineno=25,
            msg="Something warning %d",
            args=(42,),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "forge.engine"
        assert parsed["message"] == "Something warning 42"
        assert "timestamp" in parsed

    def test_json_formatter_sanitizes_extra_fields(self):
        formatter = ForgeJsonFormatter()
        record = logging.LogRecord(
            name="forge.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=30,
            msg="Task finished",
            args=(),
            exc_info=None,
        )
        record.auth_token = "ghp_1234567890abcdef"
        record.user_id = 99
        record.params = {"api_key": "topsecret", "timeout": 30}

        output = formatter.format(record)
        parsed = json.loads(output)
        assert "extra" in parsed
        assert parsed["extra"]["user_id"] == 99
        assert parsed["extra"]["auth_token"] == "***"
        assert parsed["extra"]["params"]["api_key"] == "***"
        assert parsed["extra"]["params"]["timeout"] == 30
        assert "ghp_1234567890abcdef" not in output
        assert "topsecret" not in output

    def test_json_formatter_with_exception(self):
        formatter = ForgeJsonFormatter()
        try:
            raise ValueError("Something broke badly")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="forge.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=45,
            msg="Fatal failure",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "ERROR"
        assert "exception" in parsed
        assert "ValueError: Something broke badly" in parsed["exception"]

    def test_get_formatter_factory(self):
        assert isinstance(get_formatter("text"), ForgeTextFormatter)
        assert isinstance(get_formatter("TEXT"), ForgeTextFormatter)
        assert isinstance(get_formatter("json"), ForgeJsonFormatter)
        assert isinstance(get_formatter("JSON"), ForgeJsonFormatter)
        assert isinstance(get_formatter("unknown"), ForgeTextFormatter)


class TestSetupLogging:
    def test_setup_logging_console_stream(self):
        buf = io.StringIO()
        logger = setup_logging(log_level="DEBUG", log_format="text", stream=buf)
        logger.debug("Debug diagnostic message")
        logger.info("Info diagnostic message")

        content = buf.getvalue()
        assert "[DEBUG]" in content
        assert "Debug diagnostic message" in content
        assert "[INFO]" in content
        assert "Info diagnostic message" in content

    def test_setup_logging_level_filtering(self):
        buf = io.StringIO()
        logger = setup_logging(log_level="WARNING", log_format="text", stream=buf)
        logger.debug("Invisible debug")
        logger.info("Invisible info")
        logger.warning("Visible warning")
        logger.error("Visible error")

        content = buf.getvalue()
        assert "Invisible debug" not in content
        assert "Invisible info" not in content
        assert "Visible warning" in content
        assert "Visible error" in content

    def test_setup_logging_with_forge_config(self):
        buf = io.StringIO()
        cfg = ForgeConfig(log_level="ERROR", log_format="json")
        logger = setup_logging(config=cfg, stream=buf)
        assert logger.level == logging.ERROR

        logger.info("Should not appear")
        logger.error("Critical failure event")

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["level"] == "ERROR"
        assert parsed["message"] == "Critical failure event"

    def test_setup_logging_file_destination(self, tmp_path: Path):
        log_file = tmp_path / "nested" / "logs" / "test.log"
        buf = io.StringIO()
        logger = setup_logging(
            log_level="INFO",
            log_format="text",
            log_file=log_file,
            stream=buf,
        )
        logger.info("Testing file destination write")

        # Check console stream
        assert "Testing file destination write" in buf.getvalue()

        # Check file contents
        assert log_file.exists()
        file_content = log_file.read_text(encoding="utf-8")
        assert "Testing file destination write" in file_content

    def test_setup_logging_file_destination_json(self, tmp_path: Path):
        log_file = tmp_path / "forge.ndjson"
        buf = io.StringIO()
        logger = setup_logging(
            log_level="INFO",
            log_format="json",
            log_file=log_file,
            stream=buf,
        )
        logger.info("JSON file log test", extra={"service": "runner", "token": "secret123"})

        assert log_file.exists()
        lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").strip().splitlines()]
        assert len(lines) == 1
        assert lines[0]["message"] == "JSON file log test"
        assert lines[0]["extra"]["service"] == "runner"
        assert lines[0]["extra"]["token"] == "***"
        assert "secret123" not in log_file.read_text(encoding="utf-8")

    def test_child_loggers_propagate_to_forge_handlers(self):
        buf = io.StringIO()
        setup_logging(log_level="DEBUG", log_format="json", stream=buf)

        engine_logger = logging.getLogger("forge.engine")
        engine_logger.debug("Task execution started", extra={"task": "download"})

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["logger"] == "forge.engine"
        assert record["level"] == "DEBUG"
        assert record["message"] == "Task execution started"
        assert record["extra"]["task"] == "download"

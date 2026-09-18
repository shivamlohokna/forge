"""Forge project configuration model.

ForgeConfig is a plain dataclass representing the resolved settings for a
Forge project.  It is intentionally flat and does NOT carry engine internals
or CLI state — it is only a value object produced by the config loader and
consumed by the CLI resolution layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ForgeConfig:
    """Resolved Forge project configuration.

    Attributes:
        database: Path to the SQLite execution store.  ``None`` means
            persistence is disabled by default.
        workers: Number of concurrent task-execution threads.
        log_level: Logging level (e.g. ``"INFO"``, ``"DEBUG"``, ``"WARNING"``, ``"ERROR"``).
        log_format: Log output format (``"text"`` or ``"json"``).
        log_file: Optional path to log file destination.
    """

    database: str | None = None
    workers: int = 1
    log_level: str = "INFO"
    log_format: str = "text"
    log_file: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ForgeConfig":
        """Construct a ForgeConfig from a raw dictionary (e.g. parsed TOML).

        Only keys that match known fields are applied; unknown keys are
        silently ignored so that future config additions don't break older
        Forge versions.

        Args:
            data: Dictionary with optional keys ``database``, ``workers``,
                ``log_level``, ``log_format``, ``log_file`` (sourced from
                the ``[forge]`` TOML section).

        Returns:
            A new ForgeConfig with defaults overridden by ``data``.
        """
        config = cls()
        if "database" in data:
            raw_db = data["database"]
            if not isinstance(raw_db, str):
                raise TypeError(
                    f"[forge] database must be a string, got {type(raw_db).__name__}"
                )
            config.database = raw_db
        if "workers" in data:
            raw_workers = data["workers"]
            if isinstance(raw_workers, bool) or not isinstance(raw_workers, int):
                raise TypeError(
                    f"[forge] workers must be an integer >= 1, got {raw_workers!r}"
                )
            if raw_workers < 1:
                raise ValueError(
                    f"[forge] workers must be >= 1, got {raw_workers}"
                )
            config.workers = raw_workers
        if "log_level" in data:
            raw_level = data["log_level"]
            if not isinstance(raw_level, str):
                raise TypeError(
                    f"[forge] log_level must be a string, got {type(raw_level).__name__}"
                )
            level_str = raw_level.upper()
            if level_str not in {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}:
                raise ValueError(
                    f"[forge] invalid log_level: {raw_level!r}"
                )
            config.log_level = "WARNING" if level_str == "WARN" else level_str
        if "log_format" in data:
            raw_format = data["log_format"]
            if not isinstance(raw_format, str):
                raise TypeError(
                    f"[forge] log_format must be a string, got {type(raw_format).__name__}"
                )
            fmt_str = raw_format.lower()
            if fmt_str not in {"text", "json"}:
                raise ValueError(
                    f"[forge] invalid log_format: {raw_format!r} (must be 'text' or 'json')"
                )
            config.log_format = fmt_str
        if "log_file" in data:
            raw_file = data["log_file"]
            if raw_file is not None and not isinstance(raw_file, str):
                raise TypeError(
                    f"[forge] log_file must be a string, got {type(raw_file).__name__}"
                )
            config.log_file = raw_file
        return config

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ForgeConfig("
            f"database={self.database!r}, "
            f"workers={self.workers}, "
            f"log_level={self.log_level!r}, "
            f"log_format={self.log_format!r}, "
            f"log_file={self.log_file!r})"
        )


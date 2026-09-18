"""Forge configuration discovery, loading, and resolution.

File discovery order (when locating ``forge.toml``):
1. Explicit ``path`` argument passed to :func:`load_config`.
2. ``FORGE_CONFIG`` environment variable.
3. Walk upward from ``cwd`` (or provided ``search_dir``) looking for
   ``forge.toml``, stopping at the filesystem root.

Value precedence for resolved settings (later wins only when explicitly set)::

    built-in default  <  forge.toml  <  environment  <  CLI flag

CLI flags apply only when the user actually supplied them.  An omitted
``--workers`` does not lock the default; ``FORGE_WORKERS`` or ``forge.toml``
can still fill the value.

Example ``forge.toml``::

    [forge]
    database = ".forge/forge.db"
    workers  = 4

    [logging]
    level = "INFO"
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

from forge.config.model import ForgeConfig

# --------------------------------------------------------------------------- #
# Sentinel file names searched in order during upward discovery
# --------------------------------------------------------------------------- #
_CONFIG_FILENAMES: tuple[str, ...] = ("forge.toml",)

_UNSET = object()


class ConfigError(Exception):
    """Raised when a forge.toml file cannot be parsed or contains invalid values."""


def _find_config_file(search_dir: Path) -> Path | None:
    """Walk upward from ``search_dir`` looking for a Forge config file.

    Stops when it reaches the filesystem root.

    Args:
        search_dir: Directory to start the upward search from.

    Returns:
        The first config file found, or ``None`` if none exists.
    """
    current = search_dir.resolve()
    while True:
        for name in _CONFIG_FILENAMES:
            candidate = current / name
            if candidate.is_file():
                return candidate
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            return None
        current = parent


def load_config(
    path: str | Path | None = None,
    search_dir: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> ForgeConfig:
    """Load project config from a TOML file (no env/CLI overlays).

    Resolution order for the *file*:
    1. Explicit ``path`` argument.
    2. ``FORGE_CONFIG`` environment variable.
    3. Auto-discovery: walk upward from ``search_dir`` (defaults to ``cwd``).
    4. Return defaults if no config file is found.

    Relative ``database`` paths in the file are resolved against the
    directory that contains the config file.

    Args:
        path: Explicit path to a ``forge.toml`` file.  If provided, the file
            must exist — a :class:`ConfigError` is raised if it does not.
        search_dir: Directory to start auto-discovery from.  Defaults to the
            current working directory.
        environment: Mapping used to read ``FORGE_CONFIG``.  Defaults to
            ``os.environ``.

    Returns:
        A :class:`ForgeConfig` populated from the discovered file, or a
        default instance if no file was found.

    Raises:
        ConfigError: If an explicit ``path`` is provided but does not exist,
            or if the TOML file is malformed, or if a config value is invalid.
    """
    env = environment if environment is not None else os.environ
    config_path: Path | None = None

    # 1. Explicit path argument
    if path is not None:
        config_path = Path(path)
        if not config_path.is_file():
            raise ConfigError(
                f"Forge config file not found: '{config_path}'"
            )

    # 2. FORGE_CONFIG env var
    if config_path is None:
        env_path = env.get("FORGE_CONFIG")
        if env_path:
            config_path = Path(env_path)
            if not config_path.is_file():
                raise ConfigError(
                    f"FORGE_CONFIG points to a non-existent file: '{config_path}'"
                )

    # 3. Auto-discovery upward from cwd / search_dir
    if config_path is None:
        start = Path(search_dir) if search_dir is not None else Path.cwd()
        config_path = _find_config_file(start)

    # 4. No config file found — return defaults
    if config_path is None:
        return ForgeConfig()

    return _parse_toml(config_path)


def resolve_config(
    *,
    cwd: str | Path | None = None,
    cli_args: Any = None,
    environment: Mapping[str, str] | None = None,
    path: str | Path | None = None,
) -> ForgeConfig:
    """Resolve final Forge settings.

    Precedence (explicit values only at each layer)::

        CLI  >  environment  >  forge.toml  >  built-in default

    Commands should consume this object rather than re-implementing
    lookup order.

    Args:
        cwd: Directory used for config-file discovery and for resolving
            relative database paths coming from the environment or CLI.
            Defaults to the current working directory.
        cli_args: ``argparse.Namespace`` or mapping.  Recognised keys:
            ``db`` / ``database``, ``workers``.  ``None`` means "not
            provided" and does not override a lower layer.
        environment: Mapping of environment variables.  Recognised keys:
            ``FORGE_CONFIG``, ``FORGE_DATABASE``, ``FORGE_WORKERS``,
            ``FORGE_LOG_LEVEL``.  Defaults to ``os.environ``.
        path: Optional explicit config-file path (same as ``load_config``).

    Returns:
        A fully resolved :class:`ForgeConfig`.

    Raises:
        ConfigError: On missing explicit files, invalid TOML, or bad values.
    """
    env = environment if environment is not None else os.environ
    base_dir = Path(cwd) if cwd is not None else Path.cwd()

    settings = load_config(path=path, search_dir=base_dir, environment=env)

    env_database = env.get("FORGE_DATABASE")
    if env_database:
        settings.database = _resolve_database_path(env_database, base_dir)

    if "FORGE_WORKERS" in env and env["FORGE_WORKERS"] != "":
        settings.workers = _parse_workers_value(
            env["FORGE_WORKERS"], source="FORGE_WORKERS"
        )

    env_level = env.get("FORGE_LOG_LEVEL")
    if env_level:
        lvl_str = str(env_level).upper()
        if lvl_str not in {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}:
            raise ConfigError(f"Invalid FORGE_LOG_LEVEL: {env_level!r}")
        settings.log_level = "WARNING" if lvl_str == "WARN" else lvl_str

    env_format = env.get("FORGE_LOG_FORMAT")
    if env_format:
        fmt_str = str(env_format).lower()
        if fmt_str not in {"text", "json"}:
            raise ConfigError(f"Invalid FORGE_LOG_FORMAT: {env_format!r} (must be 'text' or 'json')")
        settings.log_format = fmt_str

    env_file = env.get("FORGE_LOG_FILE")
    if env_file:
        settings.log_file = _resolve_database_path(str(env_file), base_dir)

    cli_database = _cli_override(cli_args, "db", "database")
    if cli_database is not _UNSET and cli_database is not None:
        settings.database = _resolve_database_path(str(cli_database), base_dir)

    cli_workers = _cli_override(cli_args, "workers")
    if cli_workers is not _UNSET and cli_workers is not None:
        settings.workers = _parse_workers_value(cli_workers, source="--workers")

    cli_log_level = _cli_override(cli_args, "log_level")
    if cli_log_level is not _UNSET and cli_log_level is not None:
        lvl_str = str(cli_log_level).upper()
        if lvl_str not in {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}:
            raise ConfigError(f"Invalid --log-level: {cli_log_level!r}")
        settings.log_level = "WARNING" if lvl_str == "WARN" else lvl_str

    cli_log_format = _cli_override(cli_args, "log_format")
    if cli_log_format is not _UNSET and cli_log_format is not None:
        fmt_str = str(cli_log_format).lower()
        if fmt_str not in {"text", "json"}:
            raise ConfigError(f"Invalid --log-format: {cli_log_format!r} (must be 'text' or 'json')")
        settings.log_format = fmt_str

    cli_log_file = _cli_override(cli_args, "log_file")
    if cli_log_file is not _UNSET and cli_log_file is not None:
        settings.log_file = _resolve_database_path(str(cli_log_file), base_dir)

    return settings


def _cli_override(cli_args: Any, *names: str) -> Any:
    """Return the first present CLI value, or ``_UNSET`` if omitted."""
    if cli_args is None:
        return _UNSET
    for name in names:
        if isinstance(cli_args, Mapping):
            if name in cli_args:
                return cli_args[name]
        elif hasattr(cli_args, name):
            return getattr(cli_args, name)
    return _UNSET


def _parse_workers_value(value: Any, *, source: str) -> int:
    """Coerce a workers value from env/CLI, rejecting invalid input."""
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError as exc:
                raise ConfigError(
                    f"{source} must be an integer >= 1, got {value!r}"
                ) from exc
        else:
            raise ConfigError(
                f"{source} must be an integer >= 1, got {value!r}"
            )
    if value < 1:
        raise ConfigError(f"{source} must be >= 1, got {value}")
    return value


def _resolve_database_path(raw: str, base_dir: Path) -> str:
    """Resolve a file or database path against ``base_dir`` when it is relative."""
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _parse_toml(config_path: Path) -> ForgeConfig:
    """Parse a ``forge.toml`` file and return a :class:`ForgeConfig`.

    Args:
        config_path: Path to an existing ``forge.toml`` file.

    Returns:
        Populated :class:`ForgeConfig`.

    Raises:
        ConfigError: If the file cannot be read or the TOML is malformed.
    """
    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Failed to parse Forge config '{config_path}': {exc}"
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Cannot read Forge config '{config_path}': {exc}"
        ) from exc

    forge_section = data.get("forge", {})
    logging_section = data.get("logging", {})

    if forge_section is None:
        forge_section = {}
    if not isinstance(forge_section, dict):
        raise ConfigError(
            f"'[forge]' section in '{config_path}' must be a table, "
            f"got {type(forge_section).__name__}"
        )

    try:
        config = ForgeConfig.from_dict(forge_section)
    except (ValueError, TypeError) as exc:
        raise ConfigError(
            f"Invalid value in '[forge]' section of '{config_path}': {exc}"
        ) from exc

    # Apply [logging] section
    if logging_section is not None:
        if not isinstance(logging_section, dict):
            raise ConfigError(
                f"'[logging]' section in '{config_path}' must be a table, "
                f"got {type(logging_section).__name__}"
            )
        if "level" in logging_section:
            raw_lvl = logging_section["level"]
            if not isinstance(raw_lvl, str):
                raise ConfigError(
                    f"Invalid value in '[logging]' section of '{config_path}': "
                    f"level must be a string, got {type(raw_lvl).__name__}"
                )
            lvl_str = raw_lvl.upper()
            if lvl_str not in {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}:
                raise ConfigError(
                    f"Invalid value in '[logging]' section of '{config_path}': "
                    f"invalid log_level: {raw_lvl!r}"
                )
            config.log_level = "WARNING" if lvl_str == "WARN" else lvl_str
        if "format" in logging_section:
            raw_fmt = logging_section["format"]
            if not isinstance(raw_fmt, str):
                raise ConfigError(
                    f"Invalid value in '[logging]' section of '{config_path}': "
                    f"format must be a string, got {type(raw_fmt).__name__}"
                )
            fmt_str = raw_fmt.lower()
            if fmt_str not in {"text", "json"}:
                raise ConfigError(
                    f"Invalid value in '[logging]' section of '{config_path}': "
                    f"invalid log_format: {raw_fmt!r} (must be 'text' or 'json')"
                )
            config.log_format = fmt_str
        if "file" in logging_section:
            raw_file = logging_section["file"]
            if raw_file is not None and not isinstance(raw_file, str):
                raise ConfigError(
                    f"Invalid value in '[logging]' section of '{config_path}': "
                    f"file must be a string, got {type(raw_file).__name__}"
                )
            config.log_file = raw_file

    if config.database:
        config.database = _resolve_database_path(
            config.database, config_path.parent
        )

    if config.log_file:
        config.log_file = _resolve_database_path(
            config.log_file, config_path.parent
        )

    return config

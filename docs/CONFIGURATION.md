# Forge Configuration Guide

Forge features a layered, hierarchical configuration system. Settings can be specified across multiple sources, allowing seamless local development, team-wide project standardization, and CI/CD environment overrides.

---

## Precedence Hierarchy

Settings are resolved in the following strict precedence order (higher tiers override lower tiers when explicitly specified):

```text
CLI Flags  >  Environment Variables  >  forge.toml Configuration File  >  Built-in Defaults
```

If an option is omitted at the CLI or Environment tier, it smoothly falls back to the value specified in `forge.toml`, or the built-in system default if no configuration file exists.

---

## Configuration File (`forge.toml`)

Forge automatically discovers `forge.toml` by walking upwards from the current working directory (`cwd`) to the filesystem root. You can also specify an explicit path using the `--config` flag or the `FORGE_CONFIG` environment variable.

### Full Example `forge.toml`

```toml
[forge]
# Path to SQLite database file for recording workflow execution runs, task attempts, and logs.
# Set to null or omit to disable persistence by default (in-memory only).
database = ".forge/execution.db"

# Default number of concurrent worker threads for DAG execution.
# Minimum value: 1. Default: 1.
workers = 4

# Project-wide default log level.
# Options: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL". Default: "INFO".
log_level = "INFO"

# Log output format.
# Options: "text", "json". Default: "text".
log_format = "text"

# Optional file path to mirror execution logs to disk.
log_file = ".forge/forge.log"

[logging]
# The [logging] section can also be used to configure log output.
level = "INFO"
format = "text"
file = ".forge/forge.log"
```

### Relative Path Resolution
All relative file paths defined in `forge.toml` (such as `database` and `log_file`) are automatically resolved relative to the directory containing the `forge.toml` file itself, making repository configurations portable across different working directories.

---

## Environment Variables

Every setting supported by `forge.toml` can be overridden using environment variables:

| Environment Variable | Description | Valid Values / Example | Default |
| :--- | :--- | :--- | :--- |
| `FORGE_CONFIG` | Explicit path to a `forge.toml` file. | `/etc/forge/forge.toml` | `None` (auto-discover) |
| `FORGE_DATABASE` | SQLite database file destination for persistence. | `.forge/runs.db` | `None` (no persistence) |
| `FORGE_WORKERS` | Number of concurrent execution threads. | Integer $\ge 1$ (e.g. `8`) | `1` |
| `FORGE_LOG_LEVEL` | Minimum severity level for emitted logs. | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `FORGE_LOG_FORMAT` | Format structure for standard output logs. | `text`, `json` | `text` |
| `FORGE_LOG_FILE` | Path to log file destination. | `/var/log/forge.log` | `None` |

---

## Command-Line Interface (CLI) Flags

CLI flags take top precedence during command execution:

| CLI Option | Equivalent Env Var | `forge.toml` Key | Description |
| :--- | :--- | :--- | :--- |
| `--db <path>` | `FORGE_DATABASE` | `forge.database` | SQLite database path for run persistence. |
| `-w`, `--workers <N>` | `FORGE_WORKERS` | `forge.workers` | Number of worker threads for parallel DAG tasks. |
| `--log-level <LVL>` | `FORGE_LOG_LEVEL` | `forge.log_level` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `--log-format <FMT>` | `FORGE_LOG_FORMAT` | `forge.log_format` | Log output style (`text`, `json`). |
| `--log-file <path>` | `FORGE_LOG_FILE` | `forge.log_file` | File destination for log output. |

### CLI Example Overrides

```bash
# Override workers and database on a single run
forge run pipeline.json --workers 8 --db /tmp/test_persist.db

# Enable JSON logging for log aggregation
forge run pipeline.json --log-format json --log-level DEBUG
```

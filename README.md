# Forge

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Typing](https://img.shields.io/badge/typing-PEP%20561-green.svg)](https://peps.python.org/pep-0561/)

**Forge** is an enterprise-grade workflow orchestration engine and CLI for defining, validating, executing, persisting, and inspecting resilient DAG workflows in Python with **zero required third-party runtime dependencies**.

---

## Key Highlights

- **Zero Runtime Dependencies**: Built entirely on standard library primitives (`sqlite3`, `urllib`, `concurrent.futures`, `tomllib`, `importlib.metadata`).
- **Resilient DAG Execution**: Sequential and concurrent thread-pool task scheduling, cycle detection (Kahn's algorithm), timeouts, configurable failure strategies (`STOP`, `CONTINUE`, `SKIP`, `RETRY`), and exponential backoff retry policies.
- **Rich Built-in Task Primitives**:
  - `FunctionTask`: Pure Python callables with context inspection and upstream result passing.
  - `ShellTask`: Operating system subprocess execution with environment, cwd, stdin, and stdout/stderr capture.
  - `FileTask`: Atomic file operations (write, read, copy, move, delete) with parent directory creation.
  - `HTTPTask`: Robust HTTP/REST calls with status validation, headers, and JSON/text handling.
- **Declarative Workflows**: Define and execute workflows in JSON and TOML (and YAML when PyYAML is installed) with pre-flight schema and safety validation.
- **Durable Persistence**: Built-in SQLite execution store recording workflow runs, task attempts, logs, and outputs.
- **Enterprise Observability**: Structured JSON and colorized text logging, sensitive token/credential masking, and engine event hooks.
- **Extensible Plugin Ecosystem**: Discovers third-party task types dynamically via standard Python package entry points (`forge.plugins`).
- **Modern CLI**: Rich command-line tools for `run`, `validate`, `history`, `inspect`, and `status`.

---

## Installation

Install Forge via `pip`:

```bash
pip install forge
```

*(Requires Python 3.11 or newer)*

---

## Quick Start

### 1. Python API

Define a workflow DAG using task objects and intuitive dependency operators (`>>` / `<<`):

```python
import sys
from forge import Engine, FileTask, FunctionTask, ShellTask, Workflow

# 1. Define tasks
t1 = FunctionTask(
    "GenerateReportData",
    fn=lambda ctx: {"project": "Forge 0.2.0", "status": "Ready for Release"},
    description="Generates release metadata dictionary",
)

t2 = FileTask(
    "SaveReport",
    operation="write",
    path="release_status.json",
    from_upstream="GenerateReportData",
    description="Persists payload to disk as JSON",
)

t3 = ShellTask(
    "VerifyReport",
    command=[sys.executable, "-c", "import json; print('Verified:', json.load(open('release_status.json'))['status'])"],
    description="Validates written report using Python subprocess",
)

# 2. Wire the DAG
# GenerateReportData -> SaveReport -> VerifyReport
t1 >> t2 >> t3

# 3. Assemble and execute workflow
workflow = Workflow("ReleasePipeline")
workflow.add_tasks(t3)  # Adding leaf tasks automatically registers dependencies!

engine = Engine(verbose=True)
result = engine.run(workflow)

print(result.summary())
```

### 2. Declarative Workflow (JSON / TOML)

Create a workflow file `workflow.json`:

```json
{
  "name": "QuickstartPipeline",
  "description": "Declarative multi-stage workflow",
  "tasks": [
    {
      "id": "write_config",
      "type": "file",
      "params": {
        "operation": "write",
        "path": "app.conf",
        "content": "ENVIRONMENT=production\nDEBUG=false\n"
      }
    },
    {
      "id": "inspect_config",
      "type": "shell",
      "depends_on": ["write_config"],
      "params": {
        "command": "cat app.conf || type app.conf"
      }
    }
  ]
}
```

Validate and run it from the command line:

```bash
# Validate workflow DAG and task configurations
forge validate workflow.json

# Execute workflow
forge run workflow.json
```

---

## Built-in Task Primitives

| Task Class | Declarative Type | Description | Key Parameters |
| :--- | :--- | :--- | :--- |
| `FunctionTask` | `function` *(programmatic)* | Runs an in-memory Python callable | `fn`, `description` |
| `ShellTask` | `shell` | Executes an OS subprocess command | `command`, `cwd`, `env`, `stdin`, `allowed_exit_codes` |
| `FileTask` | `file` | Performs atomic filesystem operations | `operation` (`read`, `write`, `copy`, `move`, `delete`), `path`, `source`, `destination`, `content` |
| `HTTPTask` | `http` | Sends HTTP requests | `url`, `method` (`GET`, `POST`, etc.), `headers`, `json_data`, `params`, `expected_status` |

---

## Command Line Interface (CLI)

The `forge` command provides end-to-end workflow management:

```bash
# Execute a workflow (Python file or declarative JSON/TOML/YAML)
forge run workflow.py
forge run pipeline.json --workers 4 --db .forge/forge.db

# Validate a workflow DAG without running it
forge validate pipeline.json

# View execution history
forge history
forge history --workflow ReleasePipeline --status SUCCESS --limit 10

# Inspect detailed results and task outputs of a run
forge inspect <run_id> --json

# Display overall project execution status and statistics
forge status
```

### Exit Codes
- `0`: Success (workflow ran and all tasks succeeded / validation passed).
- `1`: Workflow failure (one or more tasks failed under a stopping failure strategy).
- `2`: Configuration or syntax error (invalid config file or malformed workflow file).
- `3`: DAG validation error (circular dependency or missing dependency).

---

## Project Configuration (`forge.toml`)

Configure project-level defaults in a `forge.toml` file located in your project root:

```toml
[forge]
database = ".forge/execution.db"
workers  = 4
log_level = "INFO"
log_format = "text" # or "json"

[logging]
level = "INFO"
format = "text"
file = ".forge/forge.log"
```

Settings are resolved in the following priority order:
1. **CLI flags** (`--db`, `--workers`, `--log-level`)
2. **Environment variables** (`FORGE_DATABASE`, `FORGE_WORKERS`, `FORGE_LOG_LEVEL`)
3. **`forge.toml` file**
4. **Built-in defaults**

For complete configuration details, see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## Plugin Ecosystem

Forge features a pluggable task architecture. Any Python package can register custom task types using standard `pyproject.toml` entry points under the `forge.plugins` group:

```toml
[project.entry-points."forge.plugins"]
github = "forge_github.plugin:GitHubPlugin"
```

Once installed, plugin task types (such as `github.create_issue`) are automatically discovered and can be used directly in declarative workflows:

```json
{
  "id": "open_release_issue",
  "type": "github.create_issue",
  "params": {
    "repository": "octocat/Hello-World",
    "title": "Release 0.2.0 is live"
  }
}
```

To learn how to author your own plugins, check out [docs/PLUGINS.md](docs/PLUGINS.md).

---

## Documentation

- [Configuration Guide](docs/CONFIGURATION.md) - Full specification of `forge.toml` and environment options.
- [Declarative Workflow Specification](docs/DECLARATIVE_SPEC.md) - Syntax, task parameters, and schemas for JSON/TOML/YAML.
- [Plugin Authoring Guide](docs/PLUGINS.md) - How to build, test, and distribute custom Forge task plugins.
- [Examples Guide](examples/README.md) - Overview of all runnable Python and declarative sample workflows.

---

## License

Forge is licensed under the [Apache License 2.0](LICENSE).

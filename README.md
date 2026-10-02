# Forge

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Typing](https://img.shields.io/badge/typing-PEP%20561-green.svg)](https://peps.python.org/pep-0561/)

---

## What is Forge?

**Forge** lets you describe a series of tasks you need done, then executes those tasks reliably, shows you exactly what happened, and preserves the execution results.

Whether you are building data processing pipelines, build and test automation, server backup tasks, or REST API workflows, Forge handles dependency ordering, concurrent task execution, retries, and persistence with **zero third-party runtime dependencies**.

---

## What Problem Does It Solve?

Single shell scripts and ad-hoc Python scripts break easily:
- Failures midway leave your system in an unknown partial state.
- Retrying a failed command requires re-running everything from scratch.
- You have no history or log of previous executions or attempt outputs.
- Complex dependencies become unmaintainable nested code.

**Forge solves this:**
- **Deterministic DAG Scheduling**: Automatically resolves task order and detects circular dependencies.
- **Durable History**: Every workflow execution, task status, duration, and output is saved in SQLite.
- **Granular Retries & Timeouts**: Automatically retry flaky network/filesystem operations with linear or exponential backoff.
- **Human-Centric CLI**: Instantly inspect status, attempt logs, and diagnostic health.

---

## Who is it For?

Forge is designed for software engineers, DevOps practitioners, and data engineers who want a lightweight, enterprise-grade workflow execution engine without the overhead of heavy cloud orchestrators like Airflow or Prefect.

---

## What Does a Normal Workflow Look Like?

You can define workflows declaratively (**JSON**, **TOML**, or **YAML**) or programmatically in pure **Python**:

```json
{
  "name": "DataPipeline",
  "description": "Fetch, transform, and report",
  "tasks": [
    {
      "id": "prepare_data",
      "type": "file",
      "params": {
        "operation": "write",
        "path": "data/input.json",
        "content": "{\"status\": \"ready\"}"
      }
    },
    {
      "id": "verify_data",
      "type": "file",
      "depends_on": ["prepare_data"],
      "params": {
        "operation": "read",
        "path": "data/input.json"
      }
    },
    {
      "id": "save_report",
      "type": "file",
      "depends_on": ["verify_data"],
      "params": {
        "operation": "write",
        "path": "data/report.json",
        "content": "{\"status\": \"SUCCESS\"}"
      }
    }
  ]
}
```

---

## 5-Minute Quickstart

### 1. Installation

Install Forge via `pip`:

```bash
pip install forge
```

*(Requires Python 3.11 or newer)*

### 2. Initialize a Project

Initialize a new Forge project with standard configuration and a sample workflow:

```bash
forge init
```

This creates:
- `forge.toml` — Project configuration
- `workflow.json` — Runnable starter workflow

### 3. Preview & Validate the Workflow

Preview the execution plan without side effects (dry-run preflight check):

```bash
forge plan workflow.json
```

Validate the workflow for missing dependencies or cycle errors without running it:

```bash
forge validate workflow.json
```

### 4. Run the Workflow

Execute the workflow and watch task execution in real time:

```bash
forge run workflow.json
```

Output:
```text
=== Workflow Execution Summary: QuickstartPipeline ===
Run ID:    run_a1b2c3d4e5f6
Workflow:  QuickstartPipeline (id: wf_12345)
Status:    SUCCESS
Duration:  0.03s
Tasks:     3 total (3 succeeded, 0 failed, 0 blocked, 0 skipped)
-------------------------------------------------------
  [SUCCESS]   prepare_data (id: prepare_data, attempts: 1, 0.01s)
  [SUCCESS]   verify_data (id: verify_data, attempts: 1, 0.01s)
  [SUCCESS]   save_report (id: save_report, attempts: 1, 0.01s)
=======================================================

Next steps:
  - Run 'forge history' to view execution log.
  - Run 'forge inspect run_a1b2c3d4e5f6' to inspect outputs.
```

### 5. View History & Inspect Results

View past runs recorded in the local SQLite execution store:

```bash
forge history
```

Inspect attempt logs and outputs for a specific run:

```bash
forge inspect run_a1b2c3d4e5f6
```

---

## CLI Discovery Features

Forge includes CLI tools for self-service discovery and health diagnostics:

```bash
# Run environment and state diagnostics
forge doctor

# List available task types (built-in and installed plugins)
forge tasks

# List or copy runnable workflow examples into your project
forge examples
forge examples --copy build_test
```

---

## Core Task Primitives

| Task Type | Class | Description | Key Parameters |
| :--- | :--- | :--- | :--- |
| `file` | `FileTask` | Atomic filesystem operations | `operation` (`read`, `write`, `copy`, `move`, `delete`), `path`, `content`, `source`, `destination` |
| `shell` | `ShellTask` | Subprocess execution | `command`, `cwd`, `env`, `stdin`, `allowed_exit_codes` |
| `http` | `HTTPTask` | REST/HTTP request execution | `url`, `method`, `headers`, `json_data`, `expected_status` |
| `function` | `FunctionTask` | Pure Python callables | `fn`, `description` *(programmatic API)* |

---

## Python API Usage

You can also assemble DAG workflows using Python code and intuitive dependency operators (`>>` / `<<`):

```python
from forge import Engine, FileTask, FunctionTask, ShellTask, Workflow

t1 = FileTask(
    "prepare_data",
    operation="write",
    path="data/input.json",
    content='{"status": "ready"}',
)

t2 = FunctionTask(
    "process_data",
    fn=lambda ctx: {"processed": True},
)

t3 = FileTask(
    "save_report",
    operation="write",
    path="data/report.json",
    content='{"status": "SUCCESS"}',
)

# Wire dependencies: prepare_data -> process_data -> save_report
t1 >> t2 >> t3

wf = Workflow("PythonPipeline")
wf.add_tasks(t3)

engine = Engine()
result = engine.run(wf)
print(result.summary())
```

---

## Project Configuration (`forge.toml`)

Customize project settings in `forge.toml`:

```toml
[forge]
database = ".forge/execution.db"
workers  = 4
log_level = "INFO"
log_format = "text"

[logging]
level = "INFO"
format = "text"
file = ".forge/forge.log"
```

Resolution precedence:
1. **CLI flags** (`--db`, `--workers`, `--log-level`)
2. **Environment variables** (`FORGE_DATABASE`, `FORGE_WORKERS`, `FORGE_LOG_LEVEL`)
3. **`forge.toml` file**
4. **Built-in defaults**

---

## Plugin Ecosystem

Forge supports third-party task extensions via standard Python entry points:

```toml
[project.entry-points."forge.plugins"]
github = "forge_github.plugin:GitHubPlugin"
```

Once installed, plugin task types are automatically discovered and can be used directly in declarative workflows:

```json
{
  "id": "open_issue",
  "type": "github.create_issue",
  "params": {
    "repository": "octocat/Hello-World",
    "title": "Release pipeline succeeded"
  }
}
```

---

## CLI Exit Codes

- `0`: Success (workflow ran and all tasks succeeded / validation passed).
- `1`: Workflow failure (one or more tasks failed under a stopping failure strategy).
- `2`: Configuration or syntax error (invalid config file or malformed workflow file).
- `3`: DAG validation error (circular dependency or missing dependency).
- `130`: Interrupted via OS signal (SIGINT / SIGTERM).

---

## Technical Documentation & Architecture

For in-depth specs and guides:
- [Workflow Authoring Guide](docs/WORKFLOW_AUTHORING.md)
- [Workflow Authoring Audit](docs/WORKFLOW_AUTHORING_AUDIT.md)
- [Configuration Guide](docs/CONFIGURATION.md)
- [Declarative Specification](docs/DECLARATIVE_SPEC.md)
- [Plugin Authoring Guide](docs/PLUGINS.md)
- [Productization & Reliability Audit](docs/PRODUCTIZATION_AUDIT.md)

---

## License

Forge is licensed under the [Apache License 2.0](LICENSE).

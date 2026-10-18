# Forge

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Typing](https://img.shields.io/badge/typing-PEP%20561-green.svg)](https://peps.python.org/pep-0561/)
[![GitHub Release](https://img.shields.io/github/v/release/shivamlohokna/forge?logo=github)](https://github.com/shivamlohokna/forge/releases/latest)

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
- **Conditional Execution & Trigger Rules**: Skip or branch tasks based on parameters, outputs, or environment variables. Trigger cleanup handlers even when upstream tasks fail.
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

> [!IMPORTANT]
> **PyPI Notice**: The package name `forge` on PyPI belongs to an unrelated Django framework. Do not run `pip install forge`. Install Forge from repository source or from the verified release wheel as detailed below.

#### Option A: Install from Source (Recommended)
Requires Python 3.11 or newer:
```bash
git clone https://github.com/shivamlohokna/forge.git
cd forge
python -m venv .venv

# Activate the virtual environment:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# Install Forge CLI & Core Engine:
python -m pip install .

# Or install with the Desktop GUI extra:
python -m pip install ".[gui]"
```

#### Option B: Install from Downloaded Wheel
Download the verified wheel from the [v0.3.0 Release](https://github.com/shivamlohokna/forge/releases/tag/v0.3.0):
```bash
python -m pip install https://github.com/shivamlohokna/forge/releases/download/v0.3.0/forge-0.3.0-py3-none-any.whl

# To include desktop GUI dependencies:
python -m pip install "PySide6>=6.5.0"
```

#### Option C: Standalone Desktop Application (Zero Python Install)
If you prefer a standalone desktop application without managing a Python environment, download a prebuilt binary from the [Forge Desktop Application](#forge-desktop-application) section below.

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

## Conditional Execution & Trigger Rules

Skip or branch tasks at runtime based on parameters, upstream outputs, or environment variables using `when` clauses. Control how downstream tasks react to upstream failures or skips with `trigger_rule`:

```json
{
  "id": "deploy_prod",
  "type": "shell",
  "depends_on": ["build"],
  "when": "{{ parameters.environment == 'production' }}",
  "params": { "command": "python deploy.py --env prod" }
}
```

| Trigger Rule | Behavior |
| :--- | :--- |
| `ALL_SUCCESS` *(default)* | All upstream dependencies must succeed |
| `ALL_DONE` | Runs after all upstream tasks complete (even if failed or skipped) — ideal for cleanup/teardown |
| `NONE_FAILED` | Runs if no upstream dependency failed (allows skipped) |
| `ONE_SUCCESS` | Runs if at least one upstream dependency succeeded |
| `ALL_FAILED` | Runs only if all upstream dependencies failed — ideal for error alerting |

See [Conditional Execution Guide](docs/CONDITIONAL_EXECUTION.md) for full reference.

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

## Forge Desktop Application

Forge Desktop provides a native graphical application for **Windows**, **macOS (Apple Silicon)**, and **Linux**:
- **Visual Workflow Editor**: Interactive task creation, dependency wiring, and instant validation.
- **Starter Templates**: 1-click templates for System Health Audits, File Backup Pipelines, and REST API Monitors.
- **Live DAG Execution Visualizer**: Real-time task progress tracking, live duration timer, and output inspection.
- **Durable History Browser**: Explore past executions, filter by status, and inspect per-task metadata.
- **Settings & Defaults**: Configure default concurrency and local storage paths.

### Standalone Desktop Installers (Zero Python Install)

Prebuilt standalone binaries are available from the [**Forge v0.3.0 Release**](https://github.com/shivamlohokna/forge/releases/tag/v0.3.0):

- **Windows (x86_64)**: [**`ForgeDesktop-0.3.0-Windows-x86_64-Setup.exe`**](https://github.com/shivamlohokna/forge/releases/download/v0.3.0/ForgeDesktop-0.3.0-Windows-x86_64-Setup.exe) (36.8 MB)  
  Setup wizard creating Start Menu and Desktop shortcuts. Silent install: `/VERYSILENT /NORESTART`.
- **macOS (Apple Silicon ARM64 only — M1/M2/M3/M4)**:  
  - [**`ForgeDesktop-0.3.0-macOS-arm64.dmg`**](https://github.com/shivamlohokna/forge/releases/download/v0.3.0/ForgeDesktop-0.3.0-macOS-arm64.dmg) (45.7 MB)
  - [**`ForgeDesktop-0.3.0-macOS-arm64.app.zip`**](https://github.com/shivamlohokna/forge/releases/download/v0.3.0/ForgeDesktop-0.3.0-macOS-arm64.app.zip) (40.2 MB)  
  *Drag to `/Applications` and launch. Requires macOS 12.0 (Monterey) or newer.*  
  > **macOS Architecture Notice**: Prebuilt macOS binaries are **Apple Silicon (`arm64`) only**. Native Intel Mac (`x86_64`) prebuilt binaries are not currently included in the published release (Apple's Rosetta 2 only translates x86_64 binaries to run on ARM64 hardware; it cannot run ARM64 binaries on Intel Macs). Intel Mac users can install and run Forge from source via Python.
- **Linux (x86_64)**: [**`ForgeDesktop-0.3.0-Linux-x86_64.AppImage`**](https://github.com/shivamlohokna/forge/releases/download/v0.3.0/ForgeDesktop-0.3.0-Linux-x86_64.AppImage) (85.2 MB)  
  Self-contained portable AppImage for Linux distributions with glibc ≥ 2.35 (e.g., Ubuntu 22.04+). Run `chmod +x` and execute directly. Requires FUSE (`libfuse2`).

### Running Forge Desktop from Source

If you have Python 3.11+ installed:
```bash
git clone https://github.com/shivamlohokna/forge.git
cd forge
python -m venv .venv

# Activate the virtual environment:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# Install Forge with GUI dependencies:
python -m pip install ".[gui]"

# Launch the desktop interface:
forge-gui
```

---

## Technical Documentation & Architecture

For in-depth specs and guides:
- [Forge Desktop Guide](docs/DESKTOP.md)
- [Workflow Authoring Guide](docs/WORKFLOW_AUTHORING.md)
- [Workflow Authoring Audit](docs/WORKFLOW_AUTHORING_AUDIT.md)
- [Configuration Guide](docs/CONFIGURATION.md)
- [Declarative Specification](docs/DECLARATIVE_SPEC.md)
- [Plugin Authoring Guide](docs/PLUGINS.md)
- [Conditional Execution & Trigger Rules](docs/CONDITIONAL_EXECUTION.md)
- [Operational Reliability Guide](docs/OPERATIONAL_RELIABILITY.md)
- [Productization & Reliability Audit](docs/PRODUCTIZATION_AUDIT.md)

---

## License

Forge is licensed under the [Apache License 2.0](LICENSE).

# Forge Examples & Demonstration Workflows

This directory contains executable reference workflows demonstrating the capabilities, APIs, and formats supported by Forge.

---

## Programmatic Python Workflows

These examples demonstrate using Forge's Python API to construct, wire, execute, and inspect DAG workflows.

### 1. `pipeline_demo.py`
Demonstrates `FunctionTask` instances passing memory payloads downstream across branching and linear pipeline stages (Extract $\to$ Clean $\to$ Compute $\to$ Report and Backup).

```bash
python examples/pipeline_demo.py
```

---

### 2. `file_pipeline_demo.py`
Demonstrates combining `FunctionTask` with `FileTask` to generate raw datasets, persist them as JSON, format Markdown summaries, and copy them into an archive directory.

```bash
python examples/file_pipeline_demo.py
```

---

### 3. `end_to_end_io_demo.py`
Demonstrates end-to-end cooperation across Python code generation, filesystem writes (`FileTask`), external process execution (`ShellTask`), and result validation.

```bash
python examples/end_to_end_io_demo.py
```

---

### 4. `full_io_pipeline_demo.py`
Comprehensive pipeline orchestrating all four task primitives:
`FunctionTask` $\to$ `HTTPTask` $\to$ `FunctionTask` $\to$ `FileTask` $\to$ `ShellTask`.

Spawns a mock HTTP server to demonstrate live network API integration.

```bash
python examples/full_io_pipeline_demo.py
```

---

## Declarative Workflows (`examples/declarative/`)

These examples demonstrate defining workflows purely as data without writing custom Python execution scripts.

### 1. `basic_workflow.json`
A multi-stage declarative JSON workflow that writes a seed file, processes it via Python subprocess, and saves the final report.

```bash
# Validate without running
forge validate examples/declarative/basic_workflow.json

# Execute
forge run examples/declarative/basic_workflow.json
```

---

### 2. `data_pipeline.toml`
A multi-stage data processing pipeline defined entirely in TOML.

```bash
# Validate
forge validate examples/declarative/data_pipeline.toml

# Execute with SQLite persistence and custom worker count
forge run examples/declarative/data_pipeline.toml --workers 2 --db .forge/demo.db
```

---

### 3. `github_plugin_workflow.json`
Demonstrates using third-party tasks contributed by the `forge-github` plugin (`github.create_issue`).

*(Requires `forge-github` to be installed: `pip install -e ./forge-github`)*

```bash
# Validate plugin task types
forge validate examples/declarative/github_plugin_workflow.json

# Execute workflow
forge run examples/declarative/github_plugin_workflow.json
```

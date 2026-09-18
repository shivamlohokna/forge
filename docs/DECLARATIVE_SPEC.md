# Declarative Workflow Specification

Forge supports defining workflows declaratively in **JSON**, **TOML**, and **YAML** (when `PyYAML` is installed). Declarative workflows allow developers to build, validate, and execute complex pipelines without writing imperative execution code.

---

## Workflow Schema Overview

A declarative workflow specification is composed of top-level metadata and a list of task objects forming a Directed Acyclic Graph (DAG).

```json
{
  "name": "PipelineName",
  "description": "Optional workflow description",
  "parameters": {
    "env": "production",
    "retries": 3
  },
  "tasks": [
    {
      "id": "task_1",
      "type": "shell",
      "description": "Task description",
      "depends_on": [],
      "failure_strategy": "STOP",
      "max_retries": 2,
      "timeout": 30.0,
      "params": {
        "command": "echo 'Starting pipeline...'"
      }
    }
  ]
}
```

---

## Top-Level Fields

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `name` | `string` | **Yes** | Human-readable name for the workflow. |
| `description` | `string` | No | Narrative summary of workflow purpose. |
| `parameters` | `object` | No | Key-value pairs accessible to task execution context. |
| `tasks` | `list[object]` | **Yes** | Array of task definitions (must contain at least 1 task). |

---

## Task Object Fields

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique identifier for the task within this workflow. |
| `type` | `string` | **Yes** | — | Registered task type (e.g. `shell`, `file`, `http`, or plugin prefix like `github.create_issue`). |
| `description` | `string` | No | `""` | Description of what this task accomplishes. |
| `depends_on` | `list[string]` | No | `[]` | List of prerequisite task `id`s that must complete successfully before this task runs. |
| `failure_strategy` | `string` | No | `"STOP"` | Engine behavior on failure: `STOP`, `CONTINUE`, `SKIP`, `RETRY`. |
| `max_retries` | `integer` | No | `0` | Maximum number of retry attempts before treating as failed ($\ge 0$). |
| `timeout` | `float` | No | `null` | Maximum duration in seconds allowed for execution ($> 0$). |
| `params` | `object` | No | `{}` | Type-specific parameters passed directly to the task factory. |

---

## Built-in Task Types & Parameters

### 1. `shell`
Executes an operating system shell command or process.

```json
{
  "id": "build_project",
  "type": "shell",
  "params": {
    "command": "python setup.py build",
    "cwd": "./src",
    "env": {
      "PYTHONUNBUFFERED": "1"
    },
    "allowed_exit_codes": [0],
    "strip_output": true
  }
}
```

- **`command`** (`string` | `list[string]`, **required**): Shell command string or argument array.
- **`cwd`** (`string`, optional): Working directory for the process.
- **`env`** (`object`, optional): Environment variable dictionary.
- **`stdin`** (`string`, optional): Stdin input data string.
- **`from_upstream`** (`string`, optional): Upstream task ID whose output string is piped to stdin.
- **`allowed_exit_codes`** (`list[int]`, default `[0]`): Non-failing return codes.

---

### 2. `file`
Performs atomic filesystem operations.

```json
{
  "id": "write_report",
  "type": "file",
  "params": {
    "operation": "write",
    "path": "dist/summary.txt",
    "content": "Pipeline completed successfully.\n"
  }
}
```

- **`operation`** (`string`, **required**): One of `"read"`, `"write"`, `"copy"`, `"move"`, `"delete"`.
- **`path`** (`string`): Target path for `read`, `write`, or `delete`.
- **`source`** (`string`): Source file path for `copy` or `move`.
- **`destination`** (`string`): Target file path for `copy` or `move`.
- **`content`** (`string` | `bytes` | `object`): Content payload for `write`.
- **`from_upstream`** (`string`, optional): Upstream task ID whose output is used as `content`.

---

### 3. `http`
Performs an HTTP request using Python's standard library `urllib`.

```json
{
  "id": "notify_webhook",
  "type": "http",
  "params": {
    "url": "https://httpbin.org/post",
    "method": "POST",
    "headers": {
      "Content-Type": "application/json"
    },
    "json_data": {
      "event": "build_complete"
    },
    "expected_status": [200, 201]
  }
}
```

- **`url`** (`string`, **required**): Full target HTTP or HTTPS URL.
- **`method`** (`string`, default `"GET"`): HTTP method (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`).
- **`headers`** (`object`, optional): HTTP request headers.
- **`params`** (`object`, optional): URL query parameters.
- **`json_data`** (`object`, optional): JSON body payload.
- **`data`** (`string` | `bytes`, optional): Raw request body.
- **`expected_status`** (`int` | `list[int]`, default `[200..299]`): Allowed HTTP status codes.

---

## Failure Strategies

| Strategy | Description |
| :--- | :--- |
| `STOP` *(default)* | Halt the entire workflow execution immediately (fail-fast). |
| `CONTINUE` | Mark this task as `FAILED`, but continue executing independent parallel DAG branches. |
| `SKIP` | Mark this task as `SKIPPED` upon failure and proceed with downstream tasks. |
| `RETRY` | Automatically retry up to `max_retries` before recording a final failure. |

---

## Validation & Safety Engine

When loading a declarative workflow via `forge validate` or `forge run`, Forge enforces strict pre-flight guarantees:

1. **Safe Primitives Only**: Declarative files cannot contain executable bytecode, callables, or arbitrary Python object injections.
2. **DAG Integrity**: Kahn's algorithm validates that the graph is free of cycles and that all `depends_on` targets exist.
3. **Type Verification**: All task `type` identifiers must match a registered built-in or loaded plugin.

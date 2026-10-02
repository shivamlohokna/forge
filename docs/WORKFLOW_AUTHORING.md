# Forge Workflow Authoring Guide

Welcome to the Forge Workflow Authoring Guide. This practical guide teaches you how to design, write, preview, and execute workflow automation pipelines using Forge.

---

## 1. The Simplest Workflow

A Forge workflow is a collection of tasks executed in a Directed Acyclic Graph (DAG). You can write workflows in declarative JSON, TOML, or YAML format.

Here is the minimal 1-task JSON workflow (`workflow.json`):

```json
{
  "name": "HelloForge",
  "description": "The simplest Forge workflow",
  "tasks": [
    {
      "id": "write_greeting",
      "type": "file",
      "params": {
        "operation": "write",
        "path": "hello.txt",
        "content": "Hello from Forge!"
      }
    }
  ]
}
```

### Previewing and Running:
```bash
# Preview execution plan without side effects
forge plan workflow.json

# Validate DAG structure
forge validate workflow.json

# Run workflow
forge run workflow.json
```

---

## 2. Multiple Tasks & Sequential Dependencies

Tasks can depend on upstream tasks using the `"depends_on"` list. Forge automatically orders task execution based on dependency constraints.

```json
{
  "name": "SequentialPipeline",
  "description": "Multi-stage pipeline with dependencies",
  "tasks": [
    {
      "id": "step_1_create_data",
      "type": "file",
      "params": {
        "operation": "write",
        "path": "data/step1.txt",
        "content": "Stage 1 complete."
      }
    },
    {
      "id": "step_2_process_data",
      "type": "file",
      "depends_on": [
        "step_1_create_data"
      ],
      "params": {
        "operation": "copy",
        "source": "data/step1.txt",
        "destination": "data/step2.txt"
      }
    }
  ]
}
```

---

## 3. Parallel Execution Batches

Independent tasks without mutual dependencies run concurrently across worker threads:

```json
{
  "name": "ParallelPipeline",
  "tasks": [
    {
      "id": "fetch_user_data",
      "type": "file",
      "params": { "operation": "write", "path": "users.json", "content": "[]" }
    },
    {
      "id": "fetch_config_data",
      "type": "file",
      "params": { "operation": "write", "path": "config.json", "content": "{}" }
    },
    {
      "id": "aggregate_results",
      "type": "file",
      "depends_on": ["fetch_user_data", "fetch_config_data"],
      "params": { "operation": "write", "path": "summary.json", "content": "Done." }
    }
  ]
}
```

---

## 4. Failure Handling Strategies

Configure how Forge responds when a task encounters an error using `"failure_strategy"`:

- `"STOP"` (default): Halt execution immediately (fail-fast).
- `"SKIP"`: Mark failed task as `SKIPPED` and continue running independent tasks.
- `"CONTINUE"`: Mark failed task as `FAILED` but continue running non-dependent tasks.

```json
{
  "id": "optional_notification",
  "type": "http",
  "failure_strategy": "CONTINUE",
  "params": {
    "url": "https://api.example.com/notify",
    "method": "POST"
  }
}
```

---

## 5. Automated Retries

Configure exponential or linear retries for transient task failures using `"retry_policy"`:

```json
{
  "id": "resilient_api_call",
  "type": "http",
  "retry_policy": {
    "max_attempts": 3,
    "delay_seconds": 2.0,
    "backoff": "exponential"
  },
  "params": {
    "url": "https://api.example.com/data",
    "method": "GET"
  }
}
```

---

## 6. Using Files (`file` task)

Supported operations: `read`, `write`, `append`, `copy`, `move`, `delete`, `exists`.

```json
{
  "id": "archive_logs",
  "type": "file",
  "params": {
    "operation": "copy",
    "source": "logs/current.log",
    "destination": "logs/archive/2026-10-03.log"
  }
}
```

---

## 7. Running Shell Commands (`shell` task)

Execute subprocess commands with exit code checks:

```json
{
  "id": "run_pytest",
  "type": "shell",
  "params": {
    "command": "pytest tests/ --tb=short",
    "cwd": ".",
    "allowed_exit_codes": [0]
  }
}
```

---

## 8. Making HTTP Requests (`http` task)

Fetch REST API data and validate status codes:

```json
{
  "id": "check_service_health",
  "type": "http",
  "params": {
    "url": "https://httpbin.org/get",
    "method": "GET",
    "headers": {
      "User-Agent": "Forge/0.2.0"
    },
    "expected_status": [200]
  }
}
```

---

## 9. Environment Variables & Runtime Options

Environment variables can be referenced in declarative workflows using `${ENV_VAR}` syntax:

```json
{
  "id": "upload_artifact",
  "type": "http",
  "params": {
    "url": "${API_ENDPOINT}/upload",
    "method": "POST",
    "headers": {
      "Authorization": "Bearer ${API_KEY}"
    }
  }
}
```

---

## 10. Programmatic Python Workflows

For complex logic, workflows can be authored programmatically in Python (`workflow.py`):

```python
from forge.core.workflow import Workflow
from forge.tasks import FunctionTask, FileTask, FileOperation

def get_workflow() -> Workflow:
    wf = Workflow(name="PythonNativePipeline")

    def process(ctx):
        return {"status": "ok", "items": [1, 2, 3]}

    task1 = FunctionTask(name="process_data", fn=process)
    task2 = FileTask(
        name="save_report",
        operation=FileOperation.WRITE,
        path="output/report.json",
        content='{"status": "complete"}'
    )

    task2.add_dependency(task1)
    wf.add_tasks(task1, task2)
    return wf
```

---

## 11. Plugins

Extend Forge with custom task types provided by Python packages (e.g. `forge-github`):

```json
{
  "id": "create_github_issue",
  "type": "github.create_issue",
  "params": {
    "repository": "myorg/myrepo",
    "title": "Automated Build Report",
    "body": "Build passed successfully."
  }
}
```

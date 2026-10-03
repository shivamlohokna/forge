# Forge Workflow Results, Outputs & Composition Manual

This document provides complete instructions for defining, consuming, and composing task outputs in Forge workflows.

---

## 1. What Outputs Are

Task outputs are structured data produced when a task finishes execution successfully. Downstream tasks in a workflow DAG can consume these outputs dynamically using template placeholders:

```json
"path": "{{ outputs.download.path }}"
```

---

## 2. Why Outputs Matter

Without outputs, workflow tasks must hard-code file paths, duplicate intermediate configuration, or rely on external scripts. Task outputs enable true task composition:
- Task A produces a file or dataset.
- Task B processes the file produced by A.
- Task C generates a summary report based on B's output.

---

## 3. Declaring Outputs

Workflows automatically expose outputs for all tasks based on their task execution results. Tasks may also optionally declare output metadata in their specification for documentation or validation:

```json
{
  "id": "fetch",
  "type": "http",
  "outputs": ["status_code", "body"]
}
```

---

## 4. Consuming Outputs

To consume an output from an upstream task, use the template syntax `{{ outputs.<task_id_or_name>.<field> }}`:

```json
{
  "id": "save",
  "type": "file",
  "depends_on": ["fetch"],
  "params": {
    "operation": "write",
    "path": "data/response.json",
    "content": "{{ outputs.fetch.body }}"
  }
}
```

---

## 5. Parameters vs Outputs

| Feature | Workflow Parameters (`parameters`) | Task Outputs (`outputs`) |
|---|---|---|
| **Origin** | Supplied at run/plan time via CLI (`--param`) or config | Produced at execution time by upstream tasks |
| **Availability** | Known pre-execution | Available dynamically as tasks complete |
| **Syntax** | `{{ parameters.key }}` or `{{ key }}` | `{{ outputs.task_id.key }}` |
| **Composition** | `{{ parameters.base_dir }}/{{ outputs.task_id.filename }}` |

---

## 6. Built-in Task Outputs

### `shell` Task Outputs
- `stdout`: Captured standard output string.
- `stderr`: Captured standard error string.
- `exit_code`: Subprocess return code (e.g. `0`).
- `command`: Original command string.
- `duration_seconds`: Execution time in seconds.

### `http` Task Outputs
- `body`: Response body text.
- `status_code`: HTTP status code integer (e.g. `200`).
- `headers`: Dictionary of response HTTP headers.
- `url`: Final request URL.
- `method`: HTTP method string.

### `file` Task Outputs
- `path`: Target file or directory path string.
- `operation`: Executed operation (`READ`, `WRITE`, `COPY`, `MOVE`, `DELETE`, `EXISTS`).
- `content`: File content text (for `READ` operation).
- `exists`: Boolean indicator (for `EXISTS` / `DELETE` operations).
- `size`: File size in bytes (if file exists).

### `function` Task Outputs
- Return value dictionary keys (if dict returned) or `result` / `value`.

---

## 7. Output Types & Type Preservation

- **Exact Match:** If a task parameter string is EXACTLY `"{{ outputs.fetch.status_code }}"`, its native type (integer `200`) is preserved.
- **String Interpolation:** If embedded in text (`"Status is {{ outputs.fetch.status_code }}"`), it is stringified (`"Status is 200"`).

---

## 8. Missing Outputs & Error Handling

If a task references an output that was not produced, Forge raises a descriptive `OutputError` before task execution:

```text
Missing output field 'filename' in task 'fetch' referenced in '{{ outputs.fetch.filename }}'.
Why: Key 'filename' not found (available keys: body, headers, status_code, url).
Next Step: Check the output keys produced by task 'fetch'.
```

---

## 9. Failed, Skipped, or Retried Tasks

- **Retries:** When a task retries, intermediate failed attempt outputs are ignored. Downstream tasks receive outputs only from the **final successful attempt**.
- **Failures / Skips:** If a task fails or is skipped, no successful output is published. Downstream dependent tasks are marked `BLOCKED` (or skipped) and will not attempt execution with missing outputs.

---

## 10. Output Size Limits & Persistence Safety

To prevent SQLite database inflation:
- Large string outputs in history records (`task_runs.output`) are capped for persistence display if they exceed safety thresholds (default: 64KB).
- In-memory output data flow between tasks during workflow execution retains complete content.

---

## 11. Security & Secrets

- Outputs are strictly **DATA**. They are never passed to `eval()` or executed as arbitrary code.
- Sensitive headers (`authorization`, `api-key`, `bearer_token`) or parameters marked `secret: true` are masked as `"********"` in plan previews, inspect commands, history records, and logs.

---

## 12. Examples

### Example 1: HTTP Fetch $\rightarrow$ File Write
```json
{
  "name": "api_fetch_and_save",
  "tasks": [
    {
      "id": "get_data",
      "type": "http",
      "params": {
        "url": "https://httpbin.org/json"
      }
    },
    {
      "id": "save_data",
      "type": "file",
      "depends_on": ["get_data"],
      "params": {
        "operation": "write",
        "path": "storage/api_response.json",
        "content": "{{ outputs.get_data.body }}"
      }
    }
  ]
}
```

### Example 2: Parameter + Output Composition
```toml
[parameters.output_dir]
type    = "string"
default = "reports"

[[tasks]]
id      = "generate"
type    = "shell"
[tasks.params]
command = "echo artifact.csv"

[[tasks]]
id          = "archive"
type        = "file"
depends_on  = ["generate"]
[tasks.params]
operation   = "write"
path        = "{{ output_dir }}/{{ outputs.generate.stdout }}"
content     = "report payload"
```

---

## 13. Troubleshooting

| Symptom | Cause | Resolution |
|---|---|---|
| `OutputError: Missing output from task 'x'` | Task `x` did not run successfully | Check upstream task status and error logs |
| `OutputError: Task 'y' references output of 'x' but 'x' is not in 'depends_on'` | Missing DAG dependency | Add `"x"` to `"depends_on"` for task `y` |
| `OutputError: Task 'x' cannot reference its own output` | Self-reference cycle | Remove `outputs.x` reference inside task `x` |

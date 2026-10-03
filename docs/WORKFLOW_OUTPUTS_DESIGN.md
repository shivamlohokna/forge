# Forge Phase 6 Design Document: Workflow Results, Outputs & Composition

## 1. Objective & Problem Statement

Workflows in Forge need to pass data seamlessly between tasks. In Phase 5, Forge introduced reusable parameterized workflows driven by runtime inputs (`--param`). In Phase 6, Forge makes workflow tasks **composable through explicit task outputs**.

A task (e.g., `download`) produces structured data upon completion. Downstream tasks (e.g., `process`, `report`) can reference and consume those outputs directly in their parameter definitions using template syntax:

```json
{
  "name": "data_pipeline",
  "tasks": [
    {
      "id": "fetch_data",
      "type": "http",
      "params": {
        "url": "https://api.example.com/data"
      }
    },
    {
      "id": "save_data",
      "type": "file",
      "depends_on": ["fetch_data"],
      "params": {
        "operation": "write",
        "path": "storage/data.json",
        "content": "{{ outputs.fetch_data.body }}"
      }
    }
  ]
}
```

---

## 2. Audit of Existing Result Model

### Existing Components
1. **`TaskResult` / `TaskAttempt`** (`forge/core/result.py`):
   - Every completed task produces a `TaskResult` containing `status`, `output`, `duration_seconds`, `error_message`, and list of `TaskAttempt` records.
2. **`ExecutionContext`** (`forge/core/task.py`):
   - Passed into `task.execute(context)`. Currently contains `parameters` dict and `upstream_results` dict.
3. **`Engine` Execution Loop** (`forge/core/engine.py`):
   - Maintains an internal `upstream_outputs` dictionary updated after each successful task execution.
4. **Persistence Layer** (`forge/persistence/models.py`):
   - `TaskRunRecord` and `TaskAttemptRecord` contain an `output` column storing JSON-serialized text.
5. **Built-in Tasks**:
   - `ShellTask` returns `ShellResult` (`command`, `exit_code`, `stdout`, `stderr`, `duration_seconds`).
   - `HTTPTask` returns `HTTPResult` (`url`, `method`, `status_code`, `headers`, `body`, `duration_seconds`).
   - `FileTask` returns `str` (path), `bytes`, or `bool`.
   - `FunctionTask` returns the python function's return value.

### Key Audit Findings & Architectural Decisons
1. **Unified Result Model**: We do **NOT** invent a second result system. Structured outputs are derived directly from the task's existing return value (`task_res.output`).
2. **Output Standardization**:
   - If a task output is an object with a `to_dict()` method (e.g. `ShellResult`, `HTTPResult`), it is converted to a dictionary.
   - If a task output is a dictionary, it is used as-is.
   - If a task output is a primitive (str, int, float, bool), it is accessible directly as `{{ outputs.<task_id> }}` or as `{{ outputs.<task_id>.value }}`.
3. **Execution Context Extension**:
   - `ExecutionContext` is enhanced with a dedicated `outputs` property (and `get_output(task_ref, key)`) mapping `task_id` and `task_name` to their structured outputs dictionary.
4. **Pre-flight & Static Plan Validation**:
   - `forge plan` and workflow loader statically analyze `{{ outputs.<task_id>.<key> }}` references.
   - Validation enforces:
     - The referenced task exists in the workflow.
     - The referenced task is an explicit upstream dependency (present in `depends_on` path).
     - Circular output dependencies are detected and rejected.

---

## 3. Explicit Task Output Specifications

### 3.1 Built-in Task Output Contracts

| Task Type | Return Object / Output Dict Structure | Key Fields Available via `{{ outputs.<task_id>.<field> }}` |
|---|---|---|
| **`shell`** | `ShellResult` | `stdout`, `stderr`, `exit_code`, `command`, `duration_seconds` |
| **`http`** | `HTTPResult` | `body`, `status_code`, `headers`, `url`, `method`, `duration_seconds` |
| **`file`** | File Operation Output | `path`, `operation`, `content` (for READ), `exists` (for EXISTS) |
| **`function`** | Callable Return Value | `result` or dictionary fields if dict returned |
| **Plugin Task** | Custom Object / Dict | Any serializable dict fields or `to_dict()` returned |

---

## 4. Output Reference & Template Substitution Engine

### 4.1 Syntax Rules
- **Task Output Reference:** `{{ outputs.<task_id_or_name>.<key> }}` or nested `{{ outputs.<task_id_or_name>.<key>.<nested_key> }}`
- **Parameter Reference:** `{{ parameters.<param_name> }}` or `{{ <param_name> }}`
- **Combined Composition:** `{{ parameters.output_dir }}/{{ outputs.build.artifact_name }}`

### 4.2 Type Preservation vs String Interpolation
- **Whole-Value Match:** `"exit_code": "{{ outputs.check.exit_code }}"` $\rightarrow$ Preserves native type (e.g., integer `0`).
- **Mixed Interpolation:** `"log": "Task exited with code {{ outputs.check.exit_code }}"` $\rightarrow$ Stringifies (`"Task exited with code 0"`).
- **Escaping:** `\{{ outputs.raw.val }}` $\rightarrow$ `{{ outputs.raw.val }}`.

### 4.3 Security & Execution Boundaries
- **DATA ONLY:** Outputs are strictly data values. They are never passed to `eval()` or executed as code.
- **No Double Substitution:** Substituted output values containing `{{ }}` strings are not recursively evaluated.
- **Secret Masking:** Sensitive headers (`authorization`, `api-key`, `bearer_token`) or parameters marked `secret: true` remain masked in plan outputs, inspect tables, logs, and database records.

---

## 5. Execution Lifecycle & Dependency Flow

```text
Parameters (--param)
      │
      ▼
Workflow Resolution
      │
      ▼
Task A Execution  ──(Success)──► Output Extracted (outputs.TaskA)
                                      │
                                      ▼
                               Dynamic Template Substitution
                                      │
                                      ▼
                               Task B Execution (consumes outputs.TaskA)
```

### Failure & Retry Semantics
1. **Retries:** When Task A fails and retries, intermediate failed attempt outputs are ignored. Downstream Task B only receives outputs from Task A's **final successful attempt**.
2. **Failures / Skips / Blocks:** If Task A fails or is skipped, no successful output is published for Task A. Task B (depending on Task A) will be marked `BLOCKED` (or skipped) and will never execute with missing outputs.

---

## 6. Persistence & Safety Limits

1. **Size Limits:** Large string outputs (e.g. huge `stdout` or HTTP `body`) in `task_runs.output` are truncated for persistence and CLI display if they exceed safety thresholds (default: 64KB), while preserving full in-memory data flow between tasks during execution.
2. **Database Schema:** Uses existing SQLite schema without breaking migrations.
3. **Concurrency Isolation:** `ExecutionContext` and output dictionaries are isolated per workflow run. Parallel tasks in `ThreadPoolExecutor` operate on thread-safe snapshots.

---

## 7. Plan & Validation Capabilities

1. **`forge plan`**:
   - Parses output references statically.
   - Renders output flow in execution summary (e.g., `Task B consumes: outputs.TaskA.path`).
   - Remains completely side-effect free.
2. **`forge validate`**:
   - Catches unknown task references (`outputs.nonexistent.field`).
   - Catches un-declared dependencies (using `outputs.TaskA` without listing `TaskA` in `depends_on`).
   - Catches malformed reference expressions before any execution begins.

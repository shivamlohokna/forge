# Workflow Parameters

Workflow parameters let you write a workflow once and run it against different inputs without editing the workflow file.

---

## 1. What Parameters Are

A **workflow parameter** is a named, typed input value declared in the workflow definition that the user supplies at runtime.

```
workflow.json          →  forge run workflow.json --param source=C:\Data
                       →  forge run workflow.json --param source=C:\Projects\App1
```

The workflow file never changes. Only the runtime inputs differ.

---

## 2. Why They Exist

Without parameters you have to either:
- Duplicate workflow files (one per environment/input), or
- Edit the workflow file before each run.

With parameters, one workflow definition produces as many executions as you need.

---

## 3. Defining Parameters

Parameters are declared in a top-level `parameters` block in any declarative workflow (JSON, TOML, YAML).

### Full specification (JSON)

```json
{
  "name": "Backup Workflow",
  "parameters": {
    "source": {
      "type": "string",
      "required": true,
      "description": "Source directory to back up"
    },
    "destination": {
      "type": "string",
      "required": true,
      "description": "Backup destination directory"
    },
    "keep_days": {
      "type": "integer",
      "default": 7,
      "description": "Number of days to retain backups"
    },
    "compress": {
      "type": "boolean",
      "default": true,
      "description": "Enable compression"
    }
  },
  "tasks": [...]
}
```

### Full specification (TOML)

```toml
[parameters.source]
type        = "string"
required    = true
description = "Source directory to back up"

[parameters.keep_days]
type        = "integer"
default     = 7
description = "Retention days"
```

### Shorthand (default-only)

For simple defaults you can use a shorthand form:

```json
"parameters": {
  "keep_days": 7,
  "verbose": false,
  "label": "default"
}
```

Forge infers the type from the default value.

---

## 4. Supplying Parameters

### CLI: `--param key=value`

```powershell
forge run backup.json --param source=C:\Data --param destination=C:\Backup
```

Repeatable: use `--param` once per value.

Short form `-p` also works:

```powershell
forge run backup.json -p source=C:\Data -p destination=C:\Backup
```

### CLI: `--params file` (parameter file)

Load multiple parameters from a JSON/TOML/YAML file:

```powershell
forge run backup.json --params production.json
```

`production.json`:
```json
{
  "source": "C:\\Data\\Production",
  "destination": "D:\\Backups\\Prod",
  "keep_days": 30
}
```

Values from `--param` override values from `--params`.

### Python API

```python
from forge.declarative import load_declarative_workflow

wf = load_declarative_workflow("backup.json", parameters={
    "source": r"C:\Data",
    "destination": r"D:\Backup",
})
```

Or via the Engine directly (for Python-defined workflows):

```python
from forge.core.engine import Engine

engine = Engine()
result = engine.run(workflow, parameters={"source": r"C:\Data"})
```

---

## 5. Defaults

If a parameter has a `default`, it is used automatically when the parameter is not supplied:

```json
"keep_days": {
  "type": "integer",
  "default": 7
}
```

Running without `--param keep_days=...` will use `7`.

---

## 6. Types

| Type | Description | Example value |
|---|---|---|
| `string` | Text value | `"hello"`, `C:\Data` |
| `integer` | Whole number | `42`, `"10"` (auto-converted) |
| `number` | Float or integer | `3.14`, `5` |
| `boolean` | True/false | `true`, `false`, `yes`, `1`, `on` |

CLI values are automatically coerced to the declared type.

---

## 7. Validation

Validation runs **before any task executes**. No partial execution occurs.

### Errors and what they mean

**Missing required parameter:**
```
Parameter "source" is required.
Why: Workflow parameter "source" is marked as required and no value or default was provided.
Next Step: Pass '--param source=<value>' when running or planning the workflow.
```

**Unknown parameter:**
```
Unknown parameter "soruce".
Why: Parameter "soruce" was supplied but is not declared in the workflow parameter specification.
Next Step: Remove unknown parameter or declare "soruce" in workflow parameters (destination, source).
```

**Type mismatch:**
```
Parameter "workers" expects integer, received "many".
Why: Cannot parse "many" as an integer.
Next Step: Pass a valid integer (e.g., --param workers=10).
```

**Invalid boolean:**
```
Parameter "enabled" expects boolean, received "maybe".
Why: Parameter "enabled" declared as boolean requires true/false.
Next Step: Pass true or false for parameter "enabled".
```

---

## 8. Parameter Substitution

Workflow fields reference parameters using `{{ param_name }}` syntax.

```json
"params": {
  "command": "rsync {{ source }} {{ destination }}"
}
```

### Type Preservation

If a field contains **only** a parameter reference (no surrounding text), the native type is preserved:

```json
"max_retries": "{{ retry_count }}"
```

If `retry_count = 3` (integer), the task receives integer `3`, not string `"3"`.

### String Interpolation

If surrounding text exists, the value is converted to a string:

```json
"description": "Backing up {{ source }} with {{ keep_days }} day retention"
```

### Escaping

To produce a literal `{{ }}` in a field, escape with a backslash:

```json
"message": "\\{{ not_a_param }}"
```

Output: `{{ not_a_param }}`

### Nested Structures

Substitution recurses into nested dictionaries and lists. Dictionary **keys** are never substituted.

---

## 9. `forge plan`

Preview the execution plan with parameters resolved:

```powershell
forge plan workflow.json --param source=C:\Data --param keep_days=14
```

Output shows:
- Declared parameters with effective resolved values
- Secret parameters masked as `********`
- Execution batches with resolved task params

```
Workflow Plan: Backup Workflow
==============================

Parameters:
  source           = 'C:\\Data'
  keep_days        = 14
  compress         = True

Execution Plan (2 tasks across 2 batches):
...
```

Missing a required parameter:

```powershell
forge plan workflow.json
```
→ exits non-zero with a parameter diagnostic. **No execution occurs.**

JSON output:

```powershell
forge plan workflow.json --param source=C:\Data --json
```

The `parameters` key in the JSON output contains masked effective values.

---

## 10. `forge run`

```powershell
forge run workflow.json --param source=C:\Data --param destination=D:\Backup
```

Parameters are resolved and validated **before any task starts**. If validation fails, the process exits with a diagnostic and no tasks execute.

---

## 11. History / Inspection Behavior

Parameter values are persisted with each run record.

**Secret parameters** (marked `secret: true`) are masked as `"********"` before persistence. The raw value is **never stored**.

Non-secret parameters are visible in `forge inspect <run_id>`.

---

## 12. Security Considerations

- Parameters are **data**, never executable code.
- No `eval()`, no Jinja2 logic, no shell expression evaluation.
- Recursive substitution is explicitly disabled (a value containing `{{ x }}` is not re-expanded).
- Secret parameters are masked in:
  - CLI plan output
  - `forge inspect` / `forge history`
  - Persisted database records
  - Log output
- Parameter values received on the CLI are treated as untrusted input.
- Path parameters are not automatically resolved relative to any directory (unlike workflow-declared relative paths, which are resolved against the workflow file's parent).

---

## 13. Common Errors

| Error | Cause | Fix |
|---|---|---|
| `Parameter "x" is required` | Required param not supplied | `--param x=<value>` |
| `Unknown parameter "typo"` | Typo in CLI param name | Check spelling against workflow `parameters` block |
| `expects integer, received "abc"` | Type mismatch | Pass a valid integer |
| `expects boolean, received "maybe"` | Invalid boolean | Use `true` or `false` |
| `Parameter file not found` | Bad `--params` path | Check file path exists |

---

## 14. Examples

### Example 1: Backup workflow

```powershell
# Back up App1
forge run examples/declarative/parameterized_backup.json ^
  --param source_file=data/app1/report.json ^
  --param backup_file=backups/app1_backup.json ^
  --param label=app1-daily

# Back up App2 — same workflow, different parameters
forge run examples/declarative/parameterized_backup.json ^
  --param source_file=data/app2/report.json ^
  --param backup_file=backups/app2_backup.json ^
  --param label=app2-daily
```

### Example 2: File processor (TOML)

```powershell
# Process report A
forge run examples/declarative/parameterized_file_processor.toml ^
  --param input_path=data/raw_a.json ^
  --param output_path=output/processed_a.txt ^
  --param label=report-A

# Process report B
forge run examples/declarative/parameterized_file_processor.toml ^
  --param input_path=data/raw_b.json ^
  --param output_path=output/processed_b.txt ^
  --param label=report-B
```

### Example 3: Preview before running

```powershell
forge plan examples/declarative/parameterized_backup.json ^
  --param source_file=data/report.json ^
  --param backup_file=backups/report_backup.json
```

### Example 4: Parameter file

`params_prod.json`:
```json
{
  "source_file": "C:\\Data\\Production\\report.json",
  "backup_file": "D:\\Backups\\report_backup.json",
  "keep_days": 30
}
```

```powershell
forge run examples/declarative/parameterized_backup.json --params params_prod.json
```

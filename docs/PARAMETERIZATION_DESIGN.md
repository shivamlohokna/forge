# Parameterized Workflows Design

## 1. Audit of Current Workflow Data Flow

Forge currently handles workflow loading and execution in the following pipeline:

```
[ Workflow File (.json/.toml/.yaml/.py) ]
                    ↓
        [ CLI Parsing (main.py) ]
                    ↓
  [ Workflow Loader (cli/loader.py) ]
                    ↓
 [ Declarative Loader (declarative/loader.py) ]
    ├─ Parsers (json, toml, yaml)
    ├─ Env Var Interpolation (${ENV_VAR})
    ├─ Schema Validation (validator.py)
    ├─ Relative Path Resolution
    └─ Task Instantiation (TaskRegistry.create)
                    ↓
       [ Workflow DAG (Workflow) ]
                    ↓
       [ Engine Execution (engine.py) ]
    └─ ExecutionContext(parameters=...) -> Task.run(context)
```

### Key Audit Findings

1. **External Runtime Values Entry**:
   - Currently, runtime execution settings enter via `ForgeConfig` (`forge.toml`) or CLI arguments (`--workers`, `--db`, `--quiet`).
   - `Engine.run(workflow, parameters=...)` accepts a runtime dictionary, but `load_workflow()` and CLI subcommands (`run`, `plan`) currently do not accept workflow-level runtime parameters from the command line.

2. **Parameter Immutability & Lifecycle**:
   - Declarative tasks (e.g. `ShellTask`, `FileTask`, `HttpTask`) receive their configuration parameters (`command`, `path`, `url`) at construction time in `load_declarative_workflow()`.
   - Environment variables are interpolated (`${ENV_VAR}`) before task construction.
   - For parameterization to work against task configuration fields, parameter substitution must happen **before** task instantiation, ensuring tasks receive fully substituted, typed parameters.

3. **Execution Context Support**:
   - `ExecutionContext` in `forge/core/task.py` already includes `parameters: dict[str, Any]`.
   - `Engine.run` merges `workflow.parameters` with runtime `parameters` and propagates them to `ExecutionContext`.
   - However, task constructors currently do not participate in workflow parameter resolution.

4. **Existing Variable / Substitution Mechanisms**:
   - `forge/declarative/interpolation.py` provides `interpolate(raw_dict)` for `${ENV_VAR}` environment variable lookups.
   - Env var interpolation uses strictly identifier-based syntax `${VAR}` and double-dollar `$${VAR}` escaping. It explicitly rejects code evaluation (`eval`).
   - Parameter substitution (`{{ param_name }}`) should follow a complementary, safe design pattern.

5. **Boundary Between Configuration and Workflow Parameters**:
   - `forge.toml` / `ForgeConfig`: Engine and CLI infrastructure settings (`database`, `workers`, `log_level`).
   - Environment variables (`${VAR}`): Infrastructure credentials or system environment settings.
   - Workflow parameters (`{{ param_name }}`): Domain-specific inputs (e.g. `source_dir`, `destination_dir`, `batch_size`).

---

## 2. Parameter Model Specification

A workflow definition can declare a top-level `parameters` block:

```json
{
  "name": "Backup Workflow",
  "parameters": {
    "source": {
      "type": "string",
      "required": true,
      "description": "Source directory to backup"
    },
    "destination": {
      "type": "string",
      "required": true,
      "description": "Target backup directory"
    },
    "retention_days": {
      "type": "integer",
      "default": 7,
      "description": "Number of days to keep backups"
    },
    "compress": {
      "type": "boolean",
      "default": true,
      "description": "Enable compression"
    },
    "api_token": {
      "type": "string",
      "required": true,
      "secret": true,
      "description": "Remote API authorization token"
    }
  },
  "tasks": [...]
}
```

Shorthand form is also supported for simple defaults:
```json
{
  "parameters": {
    "retention_days": 7,
    "compress": true
  }
}
```

### Parameter Specification Fields

| Field | Type | Description | Default |
|---|---|---|---|
| `type` | `string` | Data type (`"string"`, `"integer"`, `"number"`, `"boolean"`) | Infer from default or `"string"` |
| `required` | `boolean` | Whether parameter must be supplied at runtime | `true` if no default, else `false` |
| `default` | `Any` | Default value when parameter is omitted | `None` |
| `description` | `string` | Human-readable explanation of parameter | `""` |
| `secret` | `boolean` | Mask parameter in logs, plans, history, and outputs | `false` |

---

## 3. Parameter Resolution & CLI Syntax

### CLI Parameter Options

1. `--param key=value` (or `-p key=value`): Repeatable key-value parameter pairs.
2. `--params path/to/params.json`: Path to a JSON, TOML, or YAML parameter file.

Example CLI invocation:
```powershell
forge run workflow.json --param source=C:\Data --param destination=C:\Backup --param retention_days=14
```

### Precedence Hierarchy
1. Explicit CLI `--param` / `--params` values (highest priority)
2. Workflow parameter `default` values declared in workflow definition
3. Missing required parameters without defaults (raises `ParameterValidationError`)

---

## 4. Parameter Validation & Error Handling

Parameter validation executes **before** any task instantiation or workflow execution.

Validation checks:
1. **Missing Required Parameter**: Parameter marked `required: true` has no default and was not provided.
2. **Unknown Parameter**: Parameter passed on CLI was not declared in the workflow parameter specification.
3. **Type Mismatch**: Value provided cannot be coerced or validated against declared `type`:
   - `integer`: Valid integer or integer string (e.g., `42`).
   - `number`: Valid float or integer (e.g., `3.14`).
   - `boolean`: `true`/`false`, `1`/`0`, `yes`/`no` (normalized to boolean).
   - `string`: Any scalar string value.

Errors adhere to the Forge diagnostic contract: **WHAT**, **WHY**, and **NEXT STEP**.

---

## 5. Parameter Substitution & Type Preservation

### Syntax & Escaping
- Substitution placeholder: `{{ param_name }}` (whitespace inside braces is trimmed).
- Escaping: `\{{ param_name }}` outputs literal `{{ param_name }}`.

### Substitution Rules & Type Preservation
1. **Whole-value replacement**: If a field string is exactly `"{{ retention_days }}"` and `retention_days` is integer `14`, the output is integer `14` (type preserved).
2. **String interpolation**: If a field string contains surrounding text (e.g. `"Copying to {{ destination }}/archive"`), values are converted to strings and interpolated.
3. **Recursive Structure Traversal**: Substitution traverses dictionary values and list elements recursively. Dictionary keys are never substituted.
4. **Untrusted Data Policy**: Parameter values are strictly treated as DATA. No Jinja logic, no expression evaluation, no `eval()`.
5. **No Double Substitution**: Substituted values containing `{{ ... }}` are not re-parsed.

---

## 6. Plan, History, and Security

1. **`forge plan` & `forge validate`**:
   - Accepts `--param` and `--params`.
   - Displays declared parameters and resolved effective values.
   - Masked parameters (`secret: true`) display as `********`.
   - Fails before displaying plan if parameter validation fails.
   - Performs no side effects, file creations, or database writes.

2. **History & Persistence**:
   - `WorkflowResult.parameters` stores effective execution parameters.
   - Any parameter marked `secret: true` is masked (`"********"`) before persistence or CLI rendering.

3. **Python API Integration**:
   - `load_workflow(path, parameters=...)` supports passing runtime parameters.
   - `load_declarative_workflow(data, registry=None, parameters=...)` resolves and validates parameters.
   - `Engine.run(workflow, parameters=...)` continues to accept runtime parameter overrides for backwards compatibility.

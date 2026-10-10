# Conditional Task Execution & Trigger Rules (Phase 7)

## Overview

Forge Phase 7 introduces **Conditional Task Execution (`when`)** and **DAG Trigger Rules (`trigger_rule`)**.

Together with **Parameters** (Phase 5) and **Workflow Outputs** (Phase 6), conditional execution enables complex branching, selective deployments, teardown/cleanup handlers, and fallback branches without writing custom orchestration code or resorting to external orchestrators.

---

## 1. Conditional Execution (`when`)

A task can define a `when` clause that determines whether the task executes or is skipped at runtime.

### Declarative Example

```json
{
  "name": "DeploymentWorkflow",
  "parameters": {
    "environment": "staging",
    "deploy": true
  },
  "tasks": [
    {
      "id": "build",
      "type": "file",
      "params": {
        "operation": "write",
        "path": "dist/bundle.txt",
        "content": "Application bundle"
      }
    },
    {
      "id": "deploy_prod",
      "type": "shell",
      "depends_on": ["build"],
      "when": "{{ parameters.environment == 'production' and parameters.deploy == true }}",
      "params": {
        "command": "python deploy.py --env prod"
      }
    },
    {
      "id": "deploy_staging",
      "type": "shell",
      "depends_on": ["build"],
      "when": "{{ parameters.environment == 'staging' and parameters.deploy == true }}",
      "params": {
        "command": "python deploy.py --env staging"
      }
    }
  ]
}
```

### Syntax and Expressions

The `when` clause can be written with or without double curly braces:
- `when: "{{ parameters.env == 'production' }}"`
- `when: "parameters.env == 'production'"`
- `when: "outputs.test.exit_code == 0"`
- `when: "parameters.count > 0 and parameters.enabled"`
- `when: true` or `when: false`

### Accessible Variables

| Namespace | Description | Example |
|---|---|---|
| `parameters.<name>` or `<name>` | Workflow runtime parameters | `parameters.environment == 'production'` |
| `outputs.<task_id>.<field>` | Structured output from upstream task | `outputs.run_tests.exit_code == 0` |
| `env.<VAR>` or `<VAR>` | System environment variables | `env.CI == 'true'` |

### Supported Operators & Types

* **Comparisons**: `==`, `!=`, `<`, `<=`, `>`, `>=`
* **Membership**: `in`, `not in` (e.g. `parameters.stage in ['qa', 'prod']`)
* **Boolean Logic**: `and`, `or`, `not`
* **Literals**: strings (`'prod'`), numbers (`42`, `3.14`), booleans (`true`/`false`), `null`/`None`.

### Security & Safety

Forge evaluates `when` expressions using an **Abstract Syntax Tree (AST) evaluator** (`forge.core.conditions`):
* **Zero Third-Party Dependencies**: Pure standard library `ast`.
* **NO `eval()` or `exec()`**: Disallowed nodes (such as function calls, comprehensions, lambdas, or imports) are rejected with a `ConditionEvaluationError`.
* **Data-Only Evaluation**: Expressions only read properties of safe primitives and context dictionaries.

---

## 2. Trigger Rules (`trigger_rule`)

By default in a DAG, tasks require all upstream dependencies to succeed. With `trigger_rule`, tasks can define custom readiness rules.

| Trigger Rule | Description | Common Use Case |
|---|---|---|
| `ALL_SUCCESS` *(default)* | All upstream dependencies must succeed. If an upstream task is skipped, downstream tasks in that branch are skipped. | Standard linear or fan-out execution. |
| `ALL_DONE` | All upstream dependencies must be terminal (`SUCCESS`, `FAILED`, `SKIPPED`, or `BLOCKED`). | Cleanup, teardown, temp file removal, post-run reporting. |
| `NONE_FAILED` | Upstream dependencies must be `SUCCESS` or `SKIPPED` (none `FAILED`). | Post-branching consolidation tasks. |
| `ONE_SUCCESS` | At least one upstream dependency must have succeeded. | Fallback / redundant mirrors or multi-source pipelines. |
| `ALL_FAILED` | All upstream dependencies must have failed. | Dedicated error-handling or incident notification tasks. |

### Teardown & Cleanup Example

```json
{
  "id": "cleanup_temp_files",
  "type": "file",
  "depends_on": ["run_integration_tests", "generate_report"],
  "trigger_rule": "all_done",
  "params": {
    "operation": "delete",
    "path": "temp/work_dir"
  }
}
```

Even if `run_integration_tests` fails with an error, `cleanup_temp_files` will execute because its trigger rule is `all_done`.

---

## 3. Python API Integration

Tasks created programmatically via the Python API support `when` and `trigger_rule`:

```python
from forge.core.workflow import Workflow
from forge.core.task import TriggerRule
from forge.tasks.shell_task import ShellTask
from forge.tasks.file_task import FileTask

wf = Workflow("ReleaseWorkflow")

test_task = ShellTask(
    name="RunTests",
    command="pytest tests/",
)

deploy_task = ShellTask(
    name="DeployProd",
    command="python deploy.py",
    when="parameters.environment == 'production'",
)
deploy_task.add_dependency(test_task)

notify_failure_task = ShellTask(
    name="NotifyOnFailure",
    command="python alert.py --failure",
    trigger_rule=TriggerRule.ALL_FAILED,
)
notify_failure_task.add_dependency(test_task)

cleanup_task = FileTask(
    name="Cleanup",
    operation="delete",
    path="tmp/build.log",
    trigger_rule=TriggerRule.ALL_DONE,
)
cleanup_task.add_dependency(test_task)

wf.add_tasks(test_task, deploy_task, notify_failure_task, cleanup_task)
```

You can also pass a custom Python callable for `when`:

```python
deploy_task = ShellTask(
    name="Deploy",
    command="python deploy.py",
    when=lambda ctx: ctx.get_param("deploy", False) and ctx.get_output("check", "exit_code") == 0,
)
```

---

## 4. CLI Experience

### Previewing in `forge plan`

`forge plan` displays `when` conditions and `trigger_rule` during dry-run preflight inspection:

```text
$ forge plan workflow.json --param environment=staging

Execution Plan (4 tasks across 3 batches):

  Batch 1:
    1. prepare_package
       type:       file
       depends on: (none)

  Batch 2:
    2. deploy_prod
       type:       file
       depends on: prepare_package
       when:       parameters.environment == 'production' and parameters.deploy == true

    3. deploy_staging
       type:       file
       depends on: prepare_package
       when:       parameters.environment == 'staging'

  Batch 3:
    4. cleanup
       type:       file
       depends on: deploy_prod, deploy_staging
       trigger:    ALL_DONE
```

### Execution Summary in `forge run`

Skipped tasks are reported with their diagnostic condition reason:

```text
=== Workflow Execution Summary: ConditionalBranchingPipeline ===
Run ID:    run_7b9e14a2f801
Workflow:  ConditionalBranchingPipeline
Status:    SUCCESS
Duration:  0.04s
Tasks:     4 total (3 succeeded, 0 failed, 0 blocked, 1 skipped)
-------------------------------------------------------
  [SUCCESS]   prepare_package (id: prepare_package, attempts: 1, 0.01s)
  [SKIPPED]   deploy_prod (id: deploy_prod, attempts: 0, 0.00s) (Condition 'parameters.environment == 'production'' evaluated to False)
  [SUCCESS]   deploy_staging (id: deploy_staging, attempts: 1, 0.01s)
  [SUCCESS]   cleanup (id: cleanup, attempts: 1, 0.01s)
=======================================================
```

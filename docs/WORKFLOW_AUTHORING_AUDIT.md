# Forge Workflow Authoring Audit

**Date**: October 2026  
**Status**: Completed (Phase 4 Hardening)

---

## 1. Product Experience Audit

Evaluating Forge from the perspective of a new developer discovering the project on GitHub today:

| Question | Current Answers & Gaps |
|---|---|
| **1. What is Forge?** | Python-native workflow engine providing DAG execution, persistence, and CLI tooling for automation pipelines. |
| **2. Why use it over shell/Python scripts?** | Structured DAG dependency resolution, automatic retries, execution persistence/telemetry, concurrency controls, and human-friendly CLI. |
| **3. What can I automate?** | Developer pipelines (build/test), file transformations, backup archives, REST API jobs, ML data prep pipelines. |
| **4. How do I create my first workflow?** | Run `forge init` to generate a project layout, edit `workflow.json`, then run `forge run workflow.json`. |
| **5. How do I know what tasks are available?** | `forge tasks` lists built-in/plugin types, but currently lacks detailed parameter schemas and minimal code snippets. |
| **6. How do dependencies work?** | Declared via `"depends_on": ["task_id"]` in declarative formats or `.add_dependency()` in Python API. |
| **7. How do I see what a workflow WILL do before executing it?** | Currently `forge validate` only checks DAG syntax/cycles. There is no dry-run execution plan command. |
| **8. How do I recover when something fails?** | `forge status`, `forge history`, and `forge inspect <run_id>` inspect failure state. Interrupted runs are recovered automatically on next run. |
| **9. Where do I find useful examples?** | `forge examples` lists catalog items, but descriptions are brief and lack structured recipe context. |
| **10. How do I adapt an example?** | `forge examples --copy <name>` copies files to workspace, but lacks structured modification guidelines. |

---

## 2. Identified Authoring Friction Points

1. **Lack of Pre-execution Visual Plan ("Dry Run")**:
   - Users currently jump directly from `forge validate` (pass/fail check) to `forge run` (side-effect execution).
   - There is no command to inspect task execution order, task parameter summaries, and dependency structures without executing side effects.

2. **Incomplete Task Discovery**:
   - `forge tasks` lists task names and single-line descriptions, but does not show available operations (e.g. for `file`: `read`, `write`, `copy`, `move`, `delete`), parameters, or minimal examples.

3. **Example Catalog Lacks Recipe Depth**:
   - Examples are basic demonstration files without real-world context (what problem it solves, credentials needed, failure modes, customization steps).

4. **Authoring Error Messages Need Guidance**:
   - Validation and loading errors identify broken tasks or missing parameters, but do not consistently provide actionable "Next step" suggestions (e.g., suggesting `forge tasks` when a task type is misspelled).

5. **`forge init` Next-Steps Clarity**:
   - Starter template is helpful, but the output summary could explain what each created file does and guide users through preflight planning.

---

## 3. Recommended Improvements (Phase 4 Plan)

1. **Enhance `forge tasks`**:
   - Show `Purpose`, `Operations`, `Key Parameters`, and a `Minimal Example` for every task type.
   - Maintain full backwards compatibility for `--json`.

2. **Enhance `forge examples`**:
   - Provide enhanced tabular summaries and support `--show <name>` for in-depth recipe inspection.
   - Upgrade all example workflows into real-world, categorized recipes with explicit metadata.

3. **Implement `forge plan <workflow>`**:
   - Add a side-effect-free workflow preflight preview command that displays execution batches, task dependencies, parameters (sanitized), and safety verification.

4. **Improve Authoring Diagnostics**:
   - Format schema and task errors into `WHAT`, `WHY`, `NEXT STEP` output.

5. **Comprehensive Documentation**:
   - Author `docs/WORKFLOW_AUTHORING.md` as a step-by-step practical guide.
   - Structure all existing examples as real-world recipes.

---

## 4. Intentionally Rejected Features

To maintain Forge's core design principles and avoid feature bloat, the following features were **explicitly rejected**:

- **Web Dashboard / UI**: Adds heavy dependencies and maintenance overhead; CLI output and JSON are sufficient.
- **Cloud Execution / Remote Daemon**: Out of scope; Forge is a local-first engine.
- **Visual Workflow Drag-and-Drop Builder**: Text-based declarative JSON/TOML/YAML and Python code are superior for source control and CI.
- **Implicit Variable Interpolation Engines**: Overcomplicates task contracts; explicit parameters remain the gold standard.

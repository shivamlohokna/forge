# Forge Productization & Reliability Audit

**Phase**: Productization and Reliability  
**Date**: October 2026  
**Status**: Initial Audit Completed  

---

## 1. Initial Test Suite Audit

Before any changes were made, the full test suite was executed:

- **Total Tests**: 353
- **Passing Tests**: 353
- **Failing Tests**: 0
- **Execution Time**: ~9.81s
- **Warnings**: 0
- **Coverage**: Core engine, task primitives (`ShellTask`, `FileTask`, `HTTPTask`, `FunctionTask`), persistence store, declarative parsers (JSON, TOML, YAML), CLI commands (`run`, `validate`, `history`, `inspect`, `status`), sanitizer, plugins, and concurrency.

### Suspicious / Fragile Areas Identified
1. **Persistence Defaults & History Disconnect**:
   - `forge run` defaults to in-memory/no persistence unless `database` is configured in `forge.toml` or `--db` is passed.
   - `forge history` defaults to checking `forge.db`.
   - **Impact**: A new user running `forge run workflow.json` followed by `forge history` gets an error that `forge.db` was not found.
2. **Task Type & Capability Discovery**:
   - Users cannot list registered task types (e.g. `file`, `shell`, `http`, `function`, plugin tasks) from the CLI without reading source code or markdown specs.
3. **Error Remediation & Human-Friendly Formatting**:
   - Errors explain *that* something failed, but often lack standard *What happened? Why? What can I do next?* structured guidance.
4. **First-Run Onboarding Flow**:
   - No `forge init` command to bootstrap a working `forge.toml` and sample workflow.
   - No `forge doctor` to verify Python version, SQLite permissions, plugin discovery, and path permissions.
   - No `forge examples` command to list or unpack runnable workflow templates.

---

## 2. Product Experience Audit (10-Question Evaluation)

| # | Question | Current Assessment | Identified Friction Point |
|---|----------|--------------------|---------------------------|
| 1 | **Can a developer understand what Forge does in under 1 minute?** | **Needs Improvement** | README starts with enterprise engine terms ("DAG workflow engine", "Kahn's algorithm") rather than developer value ("Run tasks reliably, see what happened, save results"). |
| 2 | **Can a developer run a useful workflow within 5 minutes?** | **Needs Improvement** | User must manually create a JSON file or write Python code. No `forge init` or `forge example` command. |
| 3 | **Is the first workflow example understandable?** | **Moderate** | Quickstart in README shows Python code and JSON with `cat app.conf \|\| type app.conf` workaround. Needs a clean, deterministic cross-platform workflow. |
| 4 | **Are errors written for humans or engine developers?** | **Needs Improvement** | Subprocess and validation errors print generic error messages without clear next steps or inspection flags. |
| 5 | **Does `forge run` clearly communicate success/failure?** | **Good** | Prints text summary, but task execution details during the run could be more visual and structured. |
| 6 | **Can users easily discover available workflow/task types?** | **Poor** | Task types are documented in `DECLARATIVE_SPEC.md`, but there is no `forge tasks` command. |
| 7 | **Can users tell where workflow history is stored?** | **Poor** | Default storage path is inconsistent between CLI commands if `forge.toml` is not present. |
| 8 | **Can users understand why a task failed?** | **Moderate** | Summaries show status, but stderr/stdout or attempt histories require running `forge inspect`. |
| 9 | **Can users recover from a failure?** | **Good** | Engine supports orphan recovery and retry strategies, but error messages don't remind users how to inspect or re-run. |
| 10 | **Can users discover advanced functionality without reading source code?** | **Moderate** | Core docs are comprehensive, but discoverability via CLI (`forge doctor`, `forge tasks`, `forge init`) is missing. |

---

## 3. Prioritized Issue Backlog

### P0 — Blocks Normal Use & Crucial UX Gaps
- **[P0-1] Default Database Path Alignment**: Ensure default database resolution is consistent across `run`, `history`, `inspect`, and `status` so `forge history` works immediately after `forge run`.

### P1 — Seriously Harms Usability & Reliability
- **[P1-1] Missing First-Run Bootstrapping (`forge init`)**: Add `forge init` to generate a standard project layout (`forge.toml` and sample workflow).
- **[P1-2] Missing Capability Discovery (`forge tasks`, `forge examples`)**: Add CLI commands to discover available task types (built-in & plugins) and runnable examples.
- **[P1-3] Diagnostic Health Check (`forge doctor`)**: Add `forge doctor` to check Python version, database access, config status, and plugin registration.
- **[P1-4] Human-Centric Error Messages**: Upgrade CLI and engine error reporting to explicitly detail *What happened*, *Why it happened*, and *What to do next*.
- **[P1-5] Canonical Beginner Workflow**: Add a dedicated, cross-platform beginner workflow example (`examples/quickstart.json` / `examples/quickstart.py`) with complete documentation and automated test verification.

### P2 — Architectural & Experience Improvements
- **[P2-1] CLI Progress Communication**: Improve visual feedback during workflow execution with clear status badges, retry alerts, and actionable next steps.
- **[P2-2] Real Use Case Example Suite**: Expand runnable examples covering project build/test, data processing, backup pipelines, HTTP API orchestration, and simple ML workflows.
- **[P2-3] README & Documentation Re-alignment**: Restructure `README.md` to lead with user benefits, 5-minute quickstart, output explanations, and CLI discovery commands.

### P3 — Polish
- **[P3-1] Help Text & Command Descriptions**: Refine CLI `--help` messages and subcommand descriptions to be clear and concise.
- **[P3-2] Path Formatting**: Ensure relative path displays in CLI output are normalized and user-friendly across OS environments.

---

## 4. Deliberately Deferred Changes (What We Are NOT Doing)

- **NO Giant Rewrites**: Existing DAG core (`Engine`, `Workflow`, `Task`, `ExecutionStore`) remains unchanged in architecture.
- **NO Third-Party Runtime Dependencies**: Forge remains 100% zero-dependency on standard library Python 3.11+.
- **NO Breaking Changes to Declarative Specification**: JSON/TOML/YAML workflow formats remain backwards-compatible.
- **NO Enterprise Web Dashboards or Remote Celery Workers**: Deferred as specified in project scope.

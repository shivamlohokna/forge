# Operational Reliability in Forge

This document details the operational safety, failure recovery, data durability, and secret protection mechanisms built into Forge (Phase 8).

---

## 1. Graceful Shutdown & Interruption Handling

Forge is designed for uninterrupted state consistency, even when executions are prematurely stopped by user intervention (e.g. `Ctrl-C` / `SIGINT`), container termination (`SIGTERM`), or runtime timeouts.

### Cancellation Lifecycle
- **Signal Handling Boundary**: OS signals (`SIGINT`, `SIGTERM`) are caught cleanly at the CLI/application layer. The signal handler notifies `engine.cancel()` and cleanly restores original signal handlers upon exit.
- **State Finalization**: If an execution is interrupted mid-run:
  1. In-flight and pending unexecuted tasks are marked `TaskStatus.CANCELLED`.
  2. The workflow status transitions to `WorkflowStatus.CANCELLED`.
  3. `workflow_result.finish(WorkflowStatus.CANCELLED)` is called and the status is persisted to SQLite (`workflow_runs`).
  4. The CLI exits with code `130` (standard 128 + 2 for `SIGINT`) and displays an actionable notice without messy Python tracebacks.
- **Responsive Retry Loops**: When tasks retry with exponential or linear delays, retry sleep loops check for cancellation in small slices (`0.1s`), ensuring `engine.cancel()` halts retrying tasks without delay.

### Process Cleanup (`ShellTask`)
- When a `ShellTask` encounters a timeout (`TaskTimeoutError`), interruption (`KeyboardInterrupt`), or system exception, the engine explicitly executes `proc.kill()` and reaps pending output pipes.
- This prevents orphaned zombie subprocesses from continuing to consume CPU, memory, or disk locks.

---

## 2. SQLite Durability, Concurrency & Locking

Forge stores all workflow telemetry in SQLite with concurrency-hardened settings:

| Pragma | Setting | Purpose |
| :--- | :--- | :--- |
| `foreign_keys` | `ON` | Enforces relational integrity across runs, tasks, and attempts |
| `journal_mode` | `WAL` | Write-Ahead Logging allows concurrent readers and writers without blocking |
| `synchronous` | `NORMAL` | Optimal write throughput while guaranteeing complete database integrity across power failures and crashes |
| `busy_timeout` | `5000` (ms) | Waits up to 5 seconds when another process holds a write lock before failing |

### Busy Retry Handling
The internal `ExecutionStore._transaction()` context manager includes automated exponential backoff with jitter (up to 5 retries) when encountering transient `sqlite3.OperationalError` (`database is locked` or `database is busy`), ensuring high stability during concurrent executions or background `forge history` inspections.

---

## 3. Secret Masking & Telemetry Sanitization

Forge strictly enforces secret masking at telemetry, logging, and persistence boundaries while ensuring tasks receive real credentials during execution.

### Masking Rules
- **Dict Key Matching**: Case-insensitive word-boundary detection masks values whose keys contain sensitive keywords:
  - `token`, `password`, `secret`, `authorization`, `api_key`, `access_token`, `private_key`, `credential`, `auth`, `passphrase`.
- **Parameter & Metadata Masking**: Parameters and metadata passed into workflows are masked with `***` before writing to SQLite.
- **Text & Error Sanitization (`sanitize_text` / `sanitize_error`)**:
  - **URLs with Credentials**: Masks passwords in URLs (e.g., `https://user:password@host/` becomes `https://user:***@host/`).
  - **Bearer / Auth Tokens**: Masks header patterns (e.g., `Bearer <token>` becomes `Bearer ***`).
  - **Key-Value Errors**: Masks assignments like `password=secret` or `api_key: secret` in exception messages and task error strings.

---

## 4. Cascaded Orphan Recovery

When a Forge worker process dies unexpectedly (e.g., `kill -9`, hardware reboot, or out-of-memory killer):
- The `workflow_runs` row remains stamped with the worker process ID (`worker_pid`).
- On the next execution, Forge checks for dead worker processes (`recover_interrupted_runs()`).
- If the recorded PID is dead:
  - The workflow run is marked `FAILED` with metadata: `process <pid> no longer exists`.
  - **Cascaded Task Recovery**: All associated `task_runs` and `task_attempts` in `RUNNING` or `PENDING` states are automatically marked `FAILED` with the explanation: `Interrupted: worker process <pid> terminated unexpectedly`.
  - Database telemetry remains completely consistent and inspectable via `forge inspect`.

---

## 5. System Health Diagnostics (`forge doctor`)

The `forge doctor` command provides end-to-end diagnostics:
1. **Python Environment**: Verifies Python 3.11+ runtime.
2. **Configuration**: Verifies `forge.toml` syntax and defaults.
3. **Database & State Durability**:
   - Tests file directory permissions.
   - Executes `PRAGMA quick_check;` to verify SQLite file integrity.
   - Verifies `WAL` journal mode and active connections.
   - Inspects for orphaned `RUNNING` workflow runs and notifies the user.
4. **Task Registry & Plugins**: Verifies discovery of built-in and third-party task types.

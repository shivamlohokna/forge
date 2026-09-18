# Changelog & Release Notes

All notable changes to the Forge platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-09-19

### Initial Public Developer Release

This is the first developer-focused release of the Forge workflow automation and execution platform.

### Added Features
- **Core Orchestration Engine**:
  - Directed Acyclic Graph (DAG) task scheduling with topological dependency resolution.
  - Cycle detection using Kahn's algorithm (`CircularDependencyError`).
  - ThreadPool-based concurrent execution and sequential execution modes.
  - Configurable failure strategies (`STOP`, `CONTINUE`, `SKIP`, `RETRY`).
  - Granular retry policies with linear and exponential backoff.
  - Execution timeout enforcement.
- **Built-in Task Primitives**:
  - `FunctionTask`: Execute pure Python callables with `ExecutionContext`.
  - `ShellTask`: Subprocess execution with stdout/stderr capture, working directory, environment overrides, and stdin piping.
  - `FileTask`: Atomic filesystem operations (`read`, `write`, `copy`, `move`, `delete`).
  - `HTTPTask`: REST/HTTP client operations with standard library `urllib`, status validation, and JSON support.
- **Declarative Workflow System**:
  - JSON, TOML, and YAML specification loaders.
  - Pre-flight schema validation and code safety guarantees (pure data primitives only).
  - Environment variable interpolation (`${ENV_VAR}`).
  - Schema-aware relative path resolution for file/shell task paths.
- **Durable Persistence**:
  - Embedded SQLite execution storage for runs, task attempts, logs, and outputs.
  - Query interfaces with filtering by status, workflow, and run ID.
- **Enterprise Observability & Security**:
  - Text and structured JSON logging.
  - Sensitive token/header sanitization (automatic redaction of passwords, authorization headers, API tokens).
  - Engine lifecycle event dispatching and callbacks (`EngineHook`).
- **Extensible Plugin Ecosystem**:
  - Automatic task type discovery via standard `forge.plugins` entry points.
  - `ForgePlugin` protocol contract with lifecycle hooks (`on_load`, `on_unload`).
  - Reference `forge-github` plugin implementation.
- **Command Line Interface (CLI)**:
  - `forge run`: Execute workflows with custom workers, database, and log configuration.
  - `forge validate`: Validate DAG structure, dependencies, and parameters without execution.
  - `forge history`: Tabular and JSON listing of past runs.
  - `forge inspect`: Detailed execution inspection of individual runs.
  - `forge status`: Project summary and run statistics dashboard.
- **Configuration Engine**:
  - Hierarchical resolution (`CLI > Environment Variables > forge.toml > Built-in Defaults`).
- **Packaging & Typing**:
  - Full PEP 561 compliance (`py.typed`).
  - Zero required third-party runtime dependencies.

---

### Known Limitations & Roadmap

Forge 0.2.0 is designed as a developer-first, CLI-driven execution engine. The following capabilities are explicitly deferred to future releases:
- Web-based visual workflow editor or dashboard.
- Distributed worker queues across multiple remote compute nodes (e.g. Celery / Kubernetes workers).
- Multi-node distributed lock consensus.
- Multi-tenant web authentication and role-based access control (RBAC).

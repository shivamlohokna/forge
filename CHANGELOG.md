# Changelog & Release Notes

All notable changes to the Forge platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - 2026-10-12

### Forge Desktop — Cross-Platform Distribution

Extends the Windows-only desktop packaging to macOS and Linux while preserving
all existing v0.2.0 functionality and the current Windows installer.

#### Added
- **macOS Distribution**:
  - Unified PyInstaller spec (`forge_desktop.spec`) now produces a proper
    `.app` bundle on macOS via `BUNDLE()` with full `Info.plist` metadata
    (`CFBundleIdentifier`, `NSHighResolutionCapable`, `LSMinimumSystemVersion`).
  - Separate CI builds for **arm64** (Apple Silicon, `macos-14`) and
    **x86_64** (Intel, `macos-13`) — no cross-compilation.
  - `scripts/build_macos_dmg.sh`: packages the `.app` into a `.dmg` with
    an Applications symlink via `hdiutil`.
  - Optional Developer ID code signing (`APPLE_SIGNING_IDENTITY` secret)
    and notarization (`APPLE_NOTARIZE_PROFILE` secret). Builds without
    secrets are ad-hoc signed and labelled `unsigned-preview`.
  - Artifact names encode OS and arch:
    `ForgeDesktop-0.3.0-macOS-arm64.dmg`,
    `ForgeDesktop-0.3.0-macOS-x86_64-unsigned-preview.dmg`.
- **Linux Distribution**:
  - PyInstaller `COLLECT()` directory bundle built on `ubuntu-22.04`
    (glibc 2.35) for broad compatibility.
  - `scripts/build_linux_appimage.sh`: builds a portable AppImage using
    the official `appimagetool`; no system Python required to run.
  - Correct `AppDir` layout: `AppRun`, `.desktop` file, `forge.png` icon,
    and `QT_PLUGIN_PATH` set in the launcher.
  - Artifact: `ForgeDesktop-0.3.0-Linux-x86_64.AppImage`.
- **Cross-Platform PyInstaller Spec**:
  - Windows-only `win_no_prefer_redirects` / `win_private_assemblies` flags
    are now conditionally set only on `win32`.
  - Icon selection is automatic: `.icns` on macOS, `.ico` on Windows,
    `.png` on Linux.
- **Cross-Platform Shell Templates**:
  - Starter workflow templates with shell tasks (`system_health_audit`,
    `data_processing_pipeline`) now emit `df -h` / `echo` commands on
    macOS/Linux instead of PowerShell, selected at import time.
- **CI Extensions** (`.github/workflows/ci.yml`):
  - `desktop-macos` job: matrix of arm64 + x86_64, tests + DMG packaging.
  - `desktop-linux` job: ubuntu-22.04, installs xcb/libfuse2 system deps,
    runs offscreen tests, builds AppImage.
  - `v*` tag trigger added so packaging jobs fire on release tags.
  - All three desktop jobs run the full `tests/test_desktop.py` suite
    with `QT_QPA_PLATFORM=offscreen` / offscreen argv injection.
- **Version bump**: `0.2.0` → `0.3.0` across `pyproject.toml`,
  `installer.iss`, and the main window sidebar label.

#### Known Limitations
- **macOS**: Unsigned/ad-hoc builds trigger Gatekeeper on first launch
  (`xattr -d com.apple.quarantine ForgeDesktop.app` to bypass). Provide
  `APPLE_SIGNING_IDENTITY` + `APPLE_NOTARIZE_PROFILE` secrets for a
  production-ready notarized build.
- **Linux**: The AppImage requires `libGL`, `libxcb`, and related
  X11/Wayland bridge libraries on the host. Pure Wayland without XWayland
  is untested. Distros with glibc < 2.35 are not supported by this build.
- **Templates**: Shell-task templates work on all platforms, but the
  generated commands reflect the OS at template load time; users targeting
  a different OS should review commands before running.
- None of the three new platform builds have been subjected to sustained
  end-to-end manual testing; they are verified at the CI packaging level
  and by the automated offscreen test suite.

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

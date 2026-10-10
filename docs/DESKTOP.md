# Forge Desktop Application Guide

Forge Desktop provides a modern, native Windows graphical user interface for designing, inspecting, and running workflows without requiring terminal interaction.

---

## 1. Architecture & Design Principles

Forge Desktop is built on top of the existing Forge core engine and declarative pipeline:

1. **Reuses Existing Core**:
   - Workflows created or loaded in the GUI are validated using `forge.declarative.validator` and executed using `forge.core.engine.Engine`.
   - Persistence connects directly to `forge.persistence.store.ExecutionStore`.
   - Shell commands, file operations, and HTTP tasks execute with the same semantics as the CLI.

2. **Decoupled GUI Dependency**:
   - The CLI and library core have **zero runtime dependencies** on PySide6 or Qt.
   - Users who only use `forge run` or import `forge` in Python do not need GUI libraries installed.
   - The desktop layer is encapsulated in `forge.desktop` and guarded by dynamic imports.

3. **Responsive UI Threading**:
   - The GUI never blocks the main Qt event loop during task execution.
   - Workflows execute inside `WorkflowRunnerThread` (`QThread`), with cross-thread signal emission via `DesktopEngineHook` updating the live UI components in real time.

---

## 2. Directory Layout & User Data

Forge Desktop stores configuration, workflows, and execution databases in the standard Windows per-user roaming application directory (`%APPDATA%\Forge`):

```
%APPDATA%\Forge\
├── workflows\             # User-created and saved declarative workflows (.json)
├── data\
│   └── forge.db           # Durable SQLite execution history store
└── config\
    └── settings.json      # Desktop application settings and concurrency defaults
```

On non-Windows platforms (development and CI testing), paths fall back gracefully to `~/.forge` or `XDG_DATA_HOME/forge`.

---

## 3. Graphical Views

Forge Desktop provides a sidebar navigation shell with five core view tabs:

### 3.1. Home View
- **Overview & Statistics**: Quick metrics showing total saved workflows, total past runs, and success rates.
- **Starter Templates**: 1-click starter workflows that load directly into the editor:
  - *System Health & Disk Audit* (multi-task PowerShell DAG)
  - *File Backup & Archiving* (atomic file write, verification, read)
  - *REST API Health Monitor* (HTTP GET with status validation)
  - *Multi-Stage Processing Pipeline* (data staging, computation, reporting)

### 3.2. Workflow Creator & Editor View
- **Metadata Configuration**: Edit workflow name, description, and worker concurrency limits.
- **Task Management**: Visual dialogs to add, edit, reorder, or remove tasks.
- **Instant Validation**: Real-time declarative DAG validation reporting cycle detection, missing dependencies, or syntax errors.
- **Live Execution Monitor**:
  - Live task status badges (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`).
  - Active execution timer with millisecond resolution.
  - Streaming execution log console with color-coded log entries.
  - Cooperative cancellation button.

### 3.3. Workflows Browser
- View all saved `.json` workflow files stored in `%APPDATA%\Forge\workflows`.
- Instant search filter by workflow name.
- Open directly into the Editor with a single click.

### 3.4. History Browser
- Tabular record of all historical workflow runs queried directly from `ExecutionStore`.
- Filter runs by status (`SUCCESS`, `FAILED`, `RUNNING`, `ALL`).
- Per-task breakdown detailing execution duration, attempt count, and output summaries.

### 3.5. Application Settings
- Inspect and configure application directories (`App Data`, `Workflows`, `Database`).
- Configure default worker concurrency.

---

## 4. Launching Forge Desktop

### From Python (with GUI extras)
```bash
pip install "forge[gui]"
forge-gui
```

### Standalone Windows Executable
In standalone distributions:
```powershell
.\dist\ForgeDesktop\ForgeDesktop.exe
```

---

## 5. Packaging & Windows Installer

Forge Desktop provides complete packaging assets:

1. **`forge_desktop.spec`**:
   - PyInstaller spec configured for `ForgeDesktop.exe`.
   - Bundles all Forge modules, declarative templates, package data, and Windows icons (`forge.ico`).
   - Generates a standalone directory bundle in `dist/ForgeDesktop/`.

2. **`installer.iss`**:
   - Inno Setup compilation script.
   - Packages `dist/ForgeDesktop/*` into a single standalone setup executable `ForgeDesktop-0.2.0-Setup.exe`.
   - Creates Start Menu and Desktop shortcuts.
   - Preserves user data in `%APPDATA%\Forge` on uninstall.

3. **Automated CI Integration**:
   - GitHub Actions workflow `.github/workflows/ci.yml` includes the `desktop-packaging` job on `windows-latest`.
   - Builds the standalone bundle, compiles the installer with Inno Setup compiler (`iscc.exe`), and uploads the setup executable artifact.

---

## 6. Testing Strategy

Desktop functionality is covered by headless unit and integration tests in `tests/test_desktop.py`:
- Configured with `-platform offscreen` to run reliably in CI without displays.
- Tests window construction, template loading, editor validation, file saving, history loading, and background execution.
- Includes dynamic import guards so tests skip gracefully if PySide6 is not present in non-GUI test environments.

# Forge Desktop Application Guide

Forge Desktop provides a modern, native graphical user interface for designing,
inspecting, and running workflows without requiring terminal interaction.
It is available for **Windows**, **macOS**, and **Linux**.


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
> [!NOTE]
> The `forge` package on PyPI is an unrelated Django project. Do not use `pip install forge`. Install from this repository's source with the GUI extra:

```bash
git clone https://github.com/shivamlohokna/forge.git
cd forge
python -m venv .venv

# Activate:
#   Windows (PowerShell): .venv\Scripts\Activate.ps1
#   macOS / Linux: source .venv/bin/activate

python -m pip install ".[gui]"
forge-gui
```

### Standalone Executable
In standalone distributions:
- **Windows**: `dist\ForgeDesktop\ForgeDesktop.exe` (or via Setup installer)
- **macOS**: `dist/ForgeDesktop.app` (or via DMG)
- **Linux**: `dist/installer/ForgeDesktop-0.3.1-Linux-x86_64.AppImage`

---

## 5. Platform Packaging & Installers

### 5.1. Windows — Inno Setup Installer
- **`forge_desktop.spec`**: PyInstaller spec → `dist/ForgeDesktop/ForgeDesktop.exe` (directory bundle).
- **`installer.iss`**: Inno Setup → `ForgeDesktop-0.3.1-Windows-x86_64-Setup.exe`.
- Creates Start Menu and Desktop shortcuts.
- Preserves `%APPDATA%\Forge` (user data) on uninstall.
- CI job: `desktop-packaging` on `windows-latest`.

### 5.2. macOS — .app Bundle + .dmg
- **`forge_desktop.spec`**: Produces `dist/ForgeDesktop.app` via `BUNDLE()` with full `Info.plist` metadata.
- **`scripts/build_macos_dmg.sh`**: Wraps the `.app` into a `.dmg` using `hdiutil create`.
- Optional `codesign` + `xcrun notarytool` support via GitHub Secrets (see Section 9).
- Unsigned builds are labelled `-unsigned-preview` and will trigger Gatekeeper.
- CI job: `desktop-macos` runs on native `macos-14` (Apple Silicon arm64). GitHub-hosted Intel macOS runners (`macos-12` and `macos-13`) have been retired by GitHub Actions; native Intel x86_64 desktop packages are not currently built in CI.

### 5.3. Linux — AppImage
- **`forge_desktop.spec`**: Produces `dist/ForgeDesktop/` (directory bundle) via `COLLECT()`.
- **`scripts/build_linux_appimage.sh`**: Creates an AppDir layout and invokes `appimagetool`.
- No Python or pip required to run the AppImage.
- CI job: `desktop-linux` on `ubuntu-22.04` (glibc 2.35).

---

## 6. Testing Strategy

Desktop functionality is covered by headless unit and integration tests in `tests/test_desktop.py`:
- Configured with `-platform offscreen` / `QT_QPA_PLATFORM=offscreen` to run in CI without displays.
- Tests: window construction, template loading, editor validation, file saving, history loading, and background workflow execution.
- Includes dynamic import guards so tests skip gracefully if PySide6 is not present.
- The full suite runs as part of every desktop CI job on **all three platforms**.

---

## 7. macOS Installation

Download the package for your architecture:

| Architecture | Package / Installation Method |
|--------------|------------------------------|
| **Apple Silicon (M1/M2/M3/M4)** | [**`ForgeDesktop-0.3.1-macOS-arm64.dmg`**](https://github.com/shivamlohokna/forge/releases/download/v0.3.1/ForgeDesktop-0.3.1-macOS-arm64.dmg) & [**`ForgeDesktop-0.3.1-macOS-arm64.app.zip`**](https://github.com/shivamlohokna/forge/releases/download/v0.3.1/ForgeDesktop-0.3.1-macOS-arm64.app.zip) |
| **Intel (x86_64)** | *Prebuilt standalone binary not available.* Install from repository source via Python 3.11+: `git clone https://github.com/shivamlohokna/forge.git && cd forge && pip install ".[gui]"` |

> [!IMPORTANT]
> **Architecture & Rosetta Notice**: Prebuilt macOS desktop binaries are exclusively built for **Apple Silicon (`arm64`)**. Apple's Rosetta 2 translation environment only runs x86_64 binaries on Apple Silicon hardware; it **cannot** translate or run ARM64 binaries on Intel Macs. Do not attempt to run the ARM64 DMG on Intel hardware. Intel Mac users should run Forge from source.

1. Open `ForgeDesktop-0.3.1-macOS-arm64.dmg` and drag `ForgeDesktop.app` into `/Applications`.
2. Double-click to launch.

> **Gatekeeper (unsigned builds)**: Right-click → Open → Open, or run:
> ```bash
> xattr -d com.apple.quarantine /Applications/ForgeDesktop.app
> ```

Minimum macOS version: **12.0 (Monterey)**.

---

## 8. Linux Installation

Download: [**`ForgeDesktop-0.3.1-Linux-x86_64.AppImage`**](https://github.com/shivamlohokna/forge/releases/download/v0.3.1/ForgeDesktop-0.3.1-Linux-x86_64.AppImage)

```bash
chmod +x ForgeDesktop-0.3.1-Linux-x86_64.AppImage
./ForgeDesktop-0.3.1-Linux-x86_64.AppImage
```

**Required host libraries** (not bundled in the AppImage):

```bash
# Ubuntu / Debian
sudo apt-get install libgl1 libglib2.0-0 libxcb1 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxkbcommon0 \
  libxkbcommon-x11-0 libegl1 libdbus-1-3 libfuse2
```

**Known limitations**: glibc ≥ 2.35 required; Wayland untested; unsigned binary.

---

## 9. Apple Developer Signing (Optional CI Secrets)

| Secret | Description |
|--------|-------------|
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: Acme Corp (XXXXXXXXXX)` |
| `APPLE_NOTARIZE_PROFILE` | Keychain profile from `xcrun notarytool store-credentials` |

When set, CI signs the `.app`, notarizes the `.dmg`, and staples the ticket.
Credentials are **never logged or exposed** in CI output.

---

## 10. CI Artifact Summary

| Job | Runner | Artifact | Format |
|-----|--------|----------|--------|
| `desktop-packaging` | `windows-latest` | `forge-desktop-windows-x86_64` | `.exe` |
| `desktop-macos` (arm64) | `macos-14` | `forge-desktop-macos-arm64` | `.dmg`, `.zip` |
| `desktop-linux` | `ubuntu-22.04` | `forge-desktop-linux-x86_64` | `.AppImage` |

---

## 11. Roadmap

| Item | Status |
|------|--------|
| Windows Inno Setup installer | ✅ v0.3.1 |
| macOS .app + .dmg (Apple Silicon arm64) | ✅ v0.3.1 |
| Linux x86_64 AppImage | ✅ v0.3.1 |
| macOS Intel (x86_64) native desktop bundle | 🔲 Requires supported Intel build infrastructure |
| macOS Developer ID signing + notarization | 🔲 Requires Apple Developer credentials |
| Linux aarch64 AppImage | 🔲 Future |
| Wayland-native support | 🔲 Future |
| Auto-update mechanism | 🔲 Future |

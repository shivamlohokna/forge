#!/usr/bin/env bash
# scripts/build_linux_appimage.sh
#
# Wraps the PyInstaller-built directory bundle into a portable AppImage for Linux.
#
# Prerequisites (installed by the CI job, not required locally):
#   pip install pyinstaller "forge[gui]"
#   FUSE or libfuse2 must be available for the final AppImage to run.
#   appimagetool is downloaded automatically.
#
# Usage:
#   bash scripts/build_linux_appimage.sh [<version>]
#   bash scripts/build_linux_appimage.sh 0.3.0
#
# Outputs:
#   dist/installer/ForgeDesktop-<version>-Linux-x86_64.AppImage
#
# Notes:
#   - The resulting AppImage is self-contained and requires no pip install.
#   - It bundles Qt shared libraries from PySide6; the host must have at
#     minimum: libGL, libXcb, libXcomposite, and their typical dependencies.
#   - Tested on Ubuntu 22.04/24.04 (glibc ≥ 2.35).  Compatibility with
#     older glibc (e.g. CentOS 7) is NOT guaranteed.
#   - The AppImage is NOT code-signed; treat as an unsigned preview on Linux.

set -euo pipefail

VERSION="${1:-0.3.0}"
ARCH="$(uname -m)"          # x86_64 or aarch64
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_DIR="$REPO_ROOT/dist/ForgeDesktop"
INSTALLER_DIR="$REPO_ROOT/dist/installer"
APPIMAGE_NAME="ForgeDesktop-${VERSION}-Linux-${ARCH}.AppImage"
APPIMAGE_PATH="$INSTALLER_DIR/$APPIMAGE_NAME"
APPDIR="$REPO_ROOT/dist/ForgeDesktop.AppDir"

echo "==> Forge Desktop Linux AppImage packaging"
echo "    Version     : $VERSION"
echo "    Arch        : $ARCH"
echo "    Bundle      : $BUNDLE_DIR"
echo "    Output      : $APPIMAGE_PATH"

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "ERROR: $BUNDLE_DIR not found. Run 'pyinstaller --noconfirm forge_desktop.spec' first."
  exit 1
fi

mkdir -p "$INSTALLER_DIR"

# ── Build the AppDir layout ─────────────────────────────────────────────────
echo "==> Building AppDir layout at $APPDIR"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"

# Copy the PyInstaller bundle into usr/bin
cp -R "$BUNDLE_DIR" "$APPDIR/usr/bin/ForgeDesktop"

# Copy application icon to the root of AppDir (required by appimagetool)
cp "$REPO_ROOT/forge/resources/icons/forge.png" "$APPDIR/forge.png"

# ── .desktop file ───────────────────────────────────────────────────────────
cat > "$APPDIR/ForgeDesktop.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=Forge Desktop
Comment=Forge Workflow Automation Desktop Application
Exec=ForgeDesktop
Icon=forge
Categories=Development;Utility;
Terminal=false
StartupWMClass=ForgeDesktop
EOF

# ── AppRun launcher ──────────────────────────────────────────────────────────
cat > "$APPDIR/AppRun" << 'EOF'
#!/usr/bin/env bash
# AppRun — launched by the AppImage runtime
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin/ForgeDesktop:$PATH"
# Prefer the bundled Qt platform plugin path
export QT_PLUGIN_PATH="$HERE/usr/bin/ForgeDesktop/PySide6/Qt/plugins"
exec "$HERE/usr/bin/ForgeDesktop/ForgeDesktop" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# ── Download appimagetool ────────────────────────────────────────────────────
APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage"
APPIMAGETOOL="$REPO_ROOT/dist/appimagetool.AppImage"

if [[ ! -x "$APPIMAGETOOL" ]]; then
  echo "==> Downloading appimagetool from $APPIMAGETOOL_URL"
  curl -fsSL -o "$APPIMAGETOOL" "$APPIMAGETOOL_URL"
  chmod +x "$APPIMAGETOOL"
fi

# ── Build AppImage ───────────────────────────────────────────────────────────
echo "==> Invoking appimagetool"
# ARCH env var tells appimagetool what arch header to embed
ARCH="$ARCH" "$APPIMAGETOOL" --no-appstream "$APPDIR" "$APPIMAGE_PATH"

echo "==> Done: $APPIMAGE_PATH"
ls -lh "$APPIMAGE_PATH"

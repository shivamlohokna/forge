#!/usr/bin/env bash
# scripts/build_macos_dmg.sh
#
# Packages the PyInstaller-built ForgeDesktop.app into a distributable .dmg.
#
# Prerequisites (installed by the CI job, not required locally):
#   pip install pyinstaller "forge[gui]"
#
# Usage:
#   bash scripts/build_macos_dmg.sh [<version>]
#   bash scripts/build_macos_dmg.sh 0.3.0
#
# Outputs:
#   dist/installer/ForgeDesktop-<version>-macOS-<arch>.dmg
#
# Environment variables (optional):
#   APPLE_SIGNING_IDENTITY — codesign identity (e.g. "Developer ID Application: …")
#   APPLE_NOTARIZE_PROFILE  — notarytool credential store profile name
#
# If APPLE_SIGNING_IDENTITY is unset the build is unsigned and labelled
# "unsigned-preview" but is otherwise functional for distribution.

set -euo pipefail

VERSION="${1:-0.3.1}"
ARCH="$(uname -m)"          # arm64 or x86_64
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_BUNDLE="$REPO_ROOT/dist/ForgeDesktop.app"
INSTALLER_DIR="$REPO_ROOT/dist/installer"
DMG_NAME="ForgeDesktop-${VERSION}-macOS-${ARCH}"
DMG_PATH="$INSTALLER_DIR/${DMG_NAME}.dmg"
VOL_NAME="Forge Desktop ${VERSION}"

echo "==> Forge Desktop macOS packaging"
echo "    Version : $VERSION"
echo "    Arch    : $ARCH"
echo "    App     : $APP_BUNDLE"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "ERROR: $APP_BUNDLE not found. Run 'pyinstaller --noconfirm forge_desktop.spec' first."
  exit 1
fi

mkdir -p "$INSTALLER_DIR"

# ── Optional: Ad-hoc or Developer ID code signing ──────────────────────────
if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  echo "==> Signing app bundle with identity: $APPLE_SIGNING_IDENTITY"
  codesign \
    --deep \
    --force \
    --options runtime \
    --sign "$APPLE_SIGNING_IDENTITY" \
    --timestamp \
    "$APP_BUNDLE"
  echo "    Signature applied."
else
  echo "    APPLE_SIGNING_IDENTITY not set — performing ad-hoc sign only."
  echo "    Distribution label: unsigned-preview"
  codesign --deep --force --sign - "$APP_BUNDLE" || true
  DMG_NAME="ForgeDesktop-${VERSION}-macOS-${ARCH}-unsigned-preview"
  DMG_PATH="$INSTALLER_DIR/${DMG_NAME}.dmg"
fi

# ── Create DMG via hdiutil ──────────────────────────────────────────────────
STAGING="$(mktemp -d)/ForgeDesktop-staging"
mkdir -p "$STAGING"
cp -R "$APP_BUNDLE" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

echo "==> Creating DMG: $DMG_PATH"
hdiutil create \
  -volname "$VOL_NAME" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

# ── Optional: Notarize ──────────────────────────────────────────────────────
if [[ -n "${APPLE_SIGNING_IDENTITY:-}" && -n "${APPLE_NOTARIZE_PROFILE:-}" ]]; then
  echo "==> Submitting DMG for notarization (profile: $APPLE_NOTARIZE_PROFILE)..."
  xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$APPLE_NOTARIZE_PROFILE" \
    --wait
  xcrun stapler staple "$DMG_PATH"
  echo "    Notarization complete."
else
  echo "    APPLE_NOTARIZE_PROFILE not set — skipping notarization."
fi

# Also package .app into .zip
echo "==> Creating ZIP of .app bundle"
(cd "$REPO_ROOT/dist" && zip -r -q -y "$INSTALLER_DIR/ForgeDesktop-${VERSION}-macOS-${ARCH}.app.zip" "ForgeDesktop.app")

# Ensure standard un-suffixed DMG also exists if named with unsigned-preview
if [[ "$DMG_PATH" != "$INSTALLER_DIR/ForgeDesktop-${VERSION}-macOS-${ARCH}.dmg" ]]; then
  cp "$DMG_PATH" "$INSTALLER_DIR/ForgeDesktop-${VERSION}-macOS-${ARCH}.dmg"
fi

echo "==> Done: $DMG_PATH"
ls -lh "$INSTALLER_DIR"

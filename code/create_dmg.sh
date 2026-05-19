#!/usr/bin/env bash
# =============================================================================
#  create_dmg.sh  —  Wraps SamplerDemo.app in a distributable .dmg
#
#  Called automatically by build_mac.sh --dmg  OR run standalone:
#    chmod +x create_dmg.sh
#    ./create_dmg.sh
# =============================================================================

set -euo pipefail

APP_NAME="SamplerDemo"
DMG_NAME="${APP_NAME}.dmg"
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/${DMG_NAME}"
STAGING="/tmp/${APP_NAME}_dmg_staging"
VOL_NAME="Sampler Demo"

if [[ ! -d "$APP_PATH" ]]; then
    echo "❌  ${APP_PATH} not found. Run build_mac.sh first."
    exit 1
fi

# ── Staging folder ────────────────────────────────────────────────────────────
rm -rf "$STAGING"
mkdir -p "$STAGING"

cp -R "$APP_PATH" "$STAGING/"

# Symlink to /Applications so user can drag & drop
ln -s /Applications "$STAGING/Applications"

# ── Create DMG ────────────────────────────────────────────────────────────────
rm -f "$DMG_PATH"

hdiutil create \
    -volname "$VOL_NAME" \
    -srcfolder "$STAGING" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

rm -rf "$STAGING"

echo "✅  DMG ready: ${DMG_PATH}"
echo "   Size: $(du -sh "$DMG_PATH" | cut -f1)"

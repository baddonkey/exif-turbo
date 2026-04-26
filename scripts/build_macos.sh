#!/usr/bin/env bash
# build_macos.sh — Build a self-contained macOS distribution for exif-turbo.
#
# Produces:
#   dist/exif-turbo.app              — app bundle (GUI)
#   dist/exif-turbo-<version>.dmg    — distributable disk image
#
# Usage:
#   bash scripts/build_macos.sh
#   bash scripts/build_macos.sh --sign "Developer ID Application: Your Name (TEAMID)"
#
# Requirements:
#   pip install pyinstaller
#   Xcode Command Line Tools (for hdiutil)
#
# Optional (for custom icon):
#   assets/icon_16.png, icon_32.png, icon_64.png, icon_128.png,
#   icon_256.png, icon_512.png  — used to generate assets/icon.icns

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Parse arguments ────────────────────────────────────────────────────────────
SIGN_IDENTITY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sign) SIGN_IDENTITY="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Read version ───────────────────────────────────────────────────────────────
VERSION=$(python3 - << 'PYEOF'
import re, pathlib
m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']",
              pathlib.Path('src/exif_turbo/__init__.py').read_text())
print(m.group(1) if m else '0.0.0')
PYEOF
)
echo "Building exif-turbo $VERSION for macOS ..."

# ── Generate .icns from logo.png ──────────────────────────────────────────────
if [[ -f src/exif_turbo/assets/logo.png ]]; then
    ICONSET_DIR="$(mktemp -d)/exif-turbo.iconset"
    mkdir -p "$ICONSET_DIR"
    export ICONSET_DIR
    python3 - << 'PYEOF'
from PIL import Image
import pathlib, os
src = pathlib.Path('src/exif_turbo/assets/logo.png')
iconset = pathlib.Path(os.environ['ICONSET_DIR'])
img = Image.open(src).convert('RGBA')
for name, size in [
    ('icon_16x16.png',16),('icon_16x16@2x.png',32),
    ('icon_32x32.png',32),('icon_32x32@2x.png',64),
    ('icon_128x128.png',128),('icon_128x128@2x.png',256),
    ('icon_256x256.png',256),('icon_256x256@2x.png',512),
    ('icon_512x512.png',512),('icon_512x512@2x.png',1024),
]:
    img.resize((size, size), Image.LANCZOS).save(iconset / name, 'PNG')
PYEOF
    mkdir -p assets
    iconutil --convert icns --output assets/icon.icns "$ICONSET_DIR"
    rm -rf "$(dirname "$ICONSET_DIR")"
    echo "  icon.icns generated from logo.png."
else
    echo "  No logo.png found — skipping .icns generation."
fi

# ── Build with PyInstaller ─────────────────────────────────────────────────────
pyinstaller \
    --noconfirm \
    --clean \
    exif-turbo-macos.spec

echo "  PyInstaller build complete."

# ── Code signing ───────────────────────────────────────────────────────────────
sign_item() {
    local path="$1"
    if [[ -n "$SIGN_IDENTITY" ]]; then
        codesign --force --options runtime \
            --sign "$SIGN_IDENTITY" \
            --timestamp \
            "$path"
    else
        codesign --force --sign - "$path"   # ad-hoc signature
    fi
}

echo "  Signing app bundle ..."
# Sign all dylibs and the main executable first, then the bundle
find "dist/exif-turbo.app" -name "*.dylib" -o -name "*.so" | while read -r lib; do
    sign_item "$lib"
done
sign_item "dist/exif-turbo.app/Contents/MacOS/exif-turbo"
sign_item "dist/exif-turbo.app"
echo "  Code signing complete."

# ── Create DMG ────────────────────────────────────────────────────────────────
DMG_NAME="exif-turbo-${VERSION}-macos.dmg"
DMG_STAGING="$(mktemp -d)/dmg-staging"
mkdir -p "$DMG_STAGING"

cp -R "dist/exif-turbo.app" "$DMG_STAGING/"

# Symlink to /Applications for drag-install
ln -s /Applications "$DMG_STAGING/Applications"

# README for the DMG
cat > "$DMG_STAGING/README.txt" <<EOF
exif-turbo $VERSION

Drag exif-turbo.app into the Applications folder to install.

For CLI indexing, use the bundled exif-turbo-index binary inside the app:
  exif-turbo.app/Contents/MacOS/exif-turbo-index --folders <dir> --db <path.db>

Full documentation: https://github.com/baddonkey/exif-turbo
EOF

# Build a compressed read-only DMG
hdiutil create \
    -volname "exif-turbo $VERSION" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -format UDZO \
    -fs HFS+ \
    "dist/$DMG_NAME"

echo ""
echo "Done! Artifacts:"
echo "  dist/exif-turbo.app"
echo "  dist/$DMG_NAME"

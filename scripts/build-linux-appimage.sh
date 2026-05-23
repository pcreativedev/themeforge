#!/usr/bin/env bash
# Local Linux AppImage build. Mirrors .github/workflows/build-linux.yml
# so contributors can reproduce CI artifacts on their machine.
#
# Requirements:
#   - x86_64 Linux
#   - Python 3.11+ with pip
#   - libfuse2 (for appimagetool runtime)
#   - wget
#
# Usage:
#   bash scripts/build-linux-appimage.sh [version]
#
# Output:
#   ThemeForge-<version>-x86_64.AppImage

set -euo pipefail

VERSION="${1:-0.0.0-dev}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    echo "✗ this script must run on x86_64 Linux" >&2
    exit 1
fi

echo "▶ installing Python deps…"
python3 -m pip install --upgrade pip
python3 -m pip install pyqt6 pyqt6-webengine pyqt6-charts pyinstaller

echo "▶ running PyInstaller…"
rm -rf build dist
pyinstaller --noconfirm --clean \
    --windowed \
    --name ThemeForge \
    --icon assets/themeforge-256.png \
    --add-data "assets:assets" \
    --add-data "context:context" \
    --collect-submodules PyQt6 \
    themeforge.py

echo "▶ downloading appimagetool…"
if [[ ! -x ./appimagetool-x86_64.AppImage ]]; then
    wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool-x86_64.AppImage
fi

echo "▶ assembling AppDir…"
APPDIR=ThemeForge.AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r dist/ThemeForge/* "$APPDIR/usr/bin/"

cp assets/themeforge-256.png "$APPDIR/themeforge.png"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp assets/themeforge-256.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/themeforge.png"

cat > "$APPDIR/themeforge.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=ThemeForge
GenericName=Theme Project Builder
Comment=PyQt6 GUI for scaffolding template projects
Exec=ThemeForge %F
Icon=themeforge
Terminal=false
Categories=Development;IDE;
Keywords=template;theme;scaffold;ai;claude;codex;
StartupNotify=true
StartupWMClass=ThemeForge
EOF
mkdir -p "$APPDIR/usr/share/applications"
cp "$APPDIR/themeforge.desktop" "$APPDIR/usr/share/applications/"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/ThemeForge" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo "▶ building AppImage…"
ARCH=x86_64 ./appimagetool-x86_64.AppImage --no-appstream "$APPDIR" \
    "ThemeForge-${VERSION}-x86_64.AppImage"

echo
echo "✓ done."
echo "  → ThemeForge-${VERSION}-x86_64.AppImage"
echo
echo "Smoke test:"
echo "  chmod +x ThemeForge-${VERSION}-x86_64.AppImage"
echo "  ./ThemeForge-${VERSION}-x86_64.AppImage"

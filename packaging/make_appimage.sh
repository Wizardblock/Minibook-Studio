#!/usr/bin/env bash
# Wraps the PyInstaller folder in dist/MiniBookStudio into one AppImage file (Linux only).
set -euo pipefail
cd "$(dirname "$0")/.."
APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r dist/MiniBookStudio/. "$APPDIR/usr/bin/"
cp assets/icon.png "$APPDIR/minibookstudio.png"
cat > "$APPDIR/minibookstudio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=MiniBook Studio
Comment=Printable cover wraps for mini books
Exec=MiniBookStudio
Icon=minibookstudio
Categories=Graphics;Office;
DESKTOP
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/MiniBookStudio" "$@"
RUN
chmod +x "$APPDIR/AppRun"
TOOL=build/appimagetool.AppImage
if [ ! -x "$TOOL" ]; then
  curl -fL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "dist/MiniBook-Studio-x86_64.AppImage"

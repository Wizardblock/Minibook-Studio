#!/usr/bin/env bash
# Wraps the PyInstaller folder in dist/MiniBookStudio into one AppImage file (Linux only).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?usage: make_appimage.sh VERSION}"
ID=io.github.wizardblock.minibookstudio
APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/metainfo"
cp -r dist/MiniBookStudio/. "$APPDIR/usr/bin/"
cp assets/icon.png "$APPDIR/$ID.png"
sed 's/^Exec=.*/Exec=MiniBookStudio/' "packaging/linux/$ID.desktop" > "$APPDIR/$ID.desktop"
cp "packaging/linux/$ID.metainfo.xml" "$APPDIR/usr/share/metainfo/$ID.appdata.xml"
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
OUT="dist/MiniBook-Studio-${VERSION}-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"
echo "$OUT"

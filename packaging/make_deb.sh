#!/usr/bin/env bash
# Builds a .deb (the installer Linux Mint, Ubuntu and Debian open with a double-click) from dist/MiniBookStudio.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?usage: make_deb.sh VERSION}"
PKG=build/deb
ID=io.github.wizardblock.minibookstudio
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt/minibook-studio" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/512x512/apps" "$PKG/usr/share/metainfo" \
         "$PKG/usr/share/doc/minibook-studio"
cp -r dist/MiniBookStudio/. "$PKG/opt/minibook-studio/"
ln -s /opt/minibook-studio/MiniBookStudio "$PKG/usr/bin/minibook-studio"
cp "packaging/linux/$ID.desktop" "$PKG/usr/share/applications/$ID.desktop"
cp "packaging/linux/$ID.metainfo.xml" "$PKG/usr/share/metainfo/$ID.metainfo.xml"
cp assets/icon.png "$PKG/usr/share/icons/hicolor/512x512/apps/$ID.png"
cp -r samples "$PKG/usr/share/doc/minibook-studio/samples"
cp LICENSE "$PKG/usr/share/doc/minibook-studio/copyright"
SIZE=$(du -sk "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: minibook-studio
Version: $VERSION
Section: graphics
Priority: optional
Architecture: amd64
Installed-Size: $SIZE
Maintainer: Wizardblock <noreply@users.noreply.github.com>
Homepage: https://github.com/Wizardblock/Minibook-Studio
Depends: libc6, libglib2.0-0, libdbus-1-3, libfontconfig1, libfreetype6, libegl1, libgl1, libnss3, libnspr4, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xfixes0, libxcb-xinerama0, libxcb-xkb1, libxcomposite1, libxdamage1, libxi6, libxrandr2, libxtst6, libasound2 | libasound2t64
Description: Printable cover wraps for mini books
 Turn your StoryGraph or Goodreads reading list into printable wraps for
 mini books: back, spine and front on one sheet, with cut and fold marks,
 covers found automatically and a live preview. Saves PDF or SVG.
CONTROL
find "$PKG" -type d -exec chmod 755 {} +
chmod 755 "$PKG/opt/minibook-studio/MiniBookStudio"
OUT="dist/minibook-studio_${VERSION}_amd64.deb"
dpkg-deb --build --root-owner-group "$PKG" "$OUT"
echo "$OUT"

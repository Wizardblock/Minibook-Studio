#!/usr/bin/env bash
# Builds the Linux installer (a .deb that Mint, Ubuntu and Debian open with a double-click).
# It holds the app's own files only. The system supplies Python and Qt (declared in Depends) and the install step
# adds the few Python libraries into a private folder, so nothing is bundled that could clash with the desktop.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?usage: make_deb.sh VERSION}"
PKG=build/deb
ID=io.github.wizardblock.minibookstudio
APP=opt/minibook-studio
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/$APP/app" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/512x512/apps" "$PKG/usr/share/metainfo" \
         "$PKG/usr/share/doc/minibook-studio"
cp -r minibook "$PKG/$APP/app/minibook"
cp minibook_gui.py "$PKG/$APP/app/"
cp -r assets "$PKG/$APP/app/assets"
find "$PKG/$APP" -name __pycache__ -prune -exec rm -rf {} +
# The libraries pip installs on first install: everything in requirements.txt above the "tests only" line, minus the
# Qt window part, which comes from the system (python3-pyqt6) so it matches the desktop's own libraries.
sed '/tests only/,$d' requirements.txt | grep -v '^#' | grep -v '^$' > "$PKG/$APP/requirements.txt"
echo "qtpy>=2.4" >> "$PKG/$APP/requirements.txt"
install -m 755 packaging/linux/minibook-studio "$PKG/usr/bin/minibook-studio"
install -m 755 packaging/linux/postinst "$PKG/DEBIAN/postinst"
install -m 755 packaging/linux/postrm "$PKG/DEBIAN/postrm"
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
Architecture: all
Installed-Size: $SIZE
Maintainer: Wizardblock <noreply@users.noreply.github.com>
Homepage: https://github.com/Wizardblock/Minibook-Studio
Depends: python3 (>= 3.10), python3-venv, python3-pyqt6, python3-pyqt6.qtwebengine, python3-pyqt6.qtwebchannel, libxcb-cursor0, libegl1, libgl1, fonts-dejavu-core
Description: Printable cover wraps for mini books
 Turn your StoryGraph or Goodreads reading list into printable wraps for
 mini books: back, spine and front on one sheet, with cut and fold marks,
 covers found automatically and a live preview. Saves PDF or SVG.
 .
 The first install downloads a few Python libraries, so it needs an internet connection.
CONTROL
find "$PKG" -type d -exec chmod 755 {} +
find "$PKG/$APP" -type f -exec chmod 644 {} +
OUT="dist/minibook-studio_${VERSION}_all.deb"
mkdir -p dist
dpkg-deb --build --root-owner-group "$PKG" "$OUT"
echo "$OUT"

#!/bin/sh
# Runs inside a plain container of some Linux distribution: installs only what a desktop has (a virtual screen,
# software graphics, the file-dialog modules that clashed before, and the libraries any desktop with a web browser
# has; NOT the xcb helper libraries, which the download must carry itself), then starts the AppImage and waits for its window.
# usage: test-generic.sh /path/to/MiniBook-Studio.AppImage
set -u
APPIMAGE="$1"
. /etc/os-release
echo "=== $PRETTY_NAME"
case "$ID ${ID_LIKE:-}" in
  *debian*|*ubuntu*)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null
    apt-get install -y -qq xvfb xdotool libgl1-mesa-dri libglx-mesa0 libegl1 gvfs procps ca-certificates fonts-dejavu-core \
      libnss3 libnspr4 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxi6 libxkbcommon0 libfontconfig1 libdbus-1-3 >/dev/null || exit 3
    apt-get install -y -qq libasound2t64 >/dev/null 2>&1 || apt-get install -y -qq libasound2 >/dev/null ;;
  *fedora*)
    dnf install -y -q xorg-x11-server-Xvfb xdotool mesa-dri-drivers mesa-libGL mesa-libEGL gvfs procps-ng dejavu-sans-fonts \
      nss alsa-lib libXcomposite libXdamage libXrandr libXtst libXi libxkbcommon fontconfig dbus-libs >/dev/null || exit 3 ;;
  *arch*)
    pacman -Syu --noconfirm --quiet xorg-server-xvfb xdotool mesa libglvnd gvfs procps-ng ttf-dejavu \
      nss alsa-lib libxcomposite libxdamage libxrandr libxtst libxi libxkbcommon fontconfig dbus >/dev/null || exit 3 ;;
  *) echo "unknown distribution $ID"; exit 2 ;;
esac
export DISPLAY=:99
Xvfb :99 -screen 0 1600x1000x24 >/dev/null 2>&1 &
sleep 3
"$APPIMAGE" --appimage-extract-and-run --selftest --log /tmp/selftest.log
st=$?
cat /tmp/selftest.log 2>/dev/null
[ $st -eq 0 ] || { echo "self-test failed"; exit 1; }
"$APPIMAGE" --appimage-extract-and-run &
found=0
for i in $(seq 1 90); do
  if xdotool search --name "MiniBook Studio" | grep -q .; then echo "window appeared after $i s"; found=1; break; fi
  sleep 1
done
LOG=$HOME/.cache/MiniBookStudio/minibook.log
echo "--- app log"; cat "$LOG" 2>/dev/null
pkill -f MiniBookStudio 2>/dev/null
[ $found -eq 1 ] || { echo "No window ever appeared"; exit 1; }
if grep -qE "undefined symbol|Could not initialize GLX|cannot open shared object|GLIBCXX|GLIBC_|neither GLX nor EGL|Failed to create (RHI|QRhi|context)|no QRhi|Attempted to render scene with no rhi" "$LOG" 2>/dev/null; then
  echo "the app log shows a library clash"; exit 1
fi
echo "OK on $PRETTY_NAME"

"""When a packaged app cannot start there is no console to show why, so say it in a message box and keep a log (PKG-07)."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
MAX_LOG_BYTES = 1_000_000


def log_path() -> Path:
    from . import settings as S
    return S.cache_dir() / "minibook.log"


def redirect_output_to_log() -> Path | None:
    """Packaged apps have no console: send what the program prints, and any crash text, to a log file."""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.write_text("", encoding="utf-8")
        stream = open(path, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
        try:                                   # the window runs in a second process and Chromium writes below Python:
            os.dup2(stream.fileno(), 1)        # catch that too, or a window that fails to open leaves no trace
            os.dup2(stream.fileno(), 2)
        except (OSError, ValueError):
            pass
        return path
    except OSError:
        return None


def webview2_installed(read_registry=None) -> bool:
    """True when the Microsoft Edge WebView2 runtime, which Windows uses for the app's window, is installed."""
    if read_registry is None:
        try:
            import winreg
        except ImportError:
            return True              # not Windows: nothing to check

        def read_registry(hive, key):
            try:
                with winreg.OpenKey(hive, key) as k:
                    return winreg.QueryValueEx(k, "pv")[0]
            except OSError:
                return None
    try:
        import winreg
        hives = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
                 (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients")]
    except ImportError:
        hives = [("HKLM32", r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
                 ("HKLM", r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
                 ("HKCU", r"Software\Microsoft\EdgeUpdate\Clients")]
    for hive, base in hives:
        version = read_registry(hive, base + "\\" + WEBVIEW2_CLIENT_ID)
        if version and version != "0.0.0.0":
            return True
    return False


def show_error(title: str, message: str) -> None:
    """A message box the person can see, whatever the system. Best effort: it never raises."""
    print(f"{title}: {message}", file=sys.stderr)
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
        elif sys.platform == "darwin":
            text = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display dialog "{text}" with title "{title}" buttons {{"OK"}} '
                            f'default button "OK" with icon stop'], check=False, timeout=120)
        else:
            for cmd in (["zenity", "--error", "--title", title, "--text", message, "--width", "420"],
                        ["kdialog", "--error", message, "--title", title],
                        ["xmessage", "-center", f"{title}\n\n{message}"]):
                try:
                    subprocess.run(cmd, check=False, timeout=120)
                    return
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
    except Exception:
        pass


MAC_MINIMUM = (13, 3)      # the window uses the web engine built into macOS; import maps (which the interface needs) arrived in 16.4


def mac_version(read=None) -> tuple[int, ...] | None:
    """The macOS version as numbers, or None when unknown (then we do not block anything)."""
    try:
        text = read() if read else __import__("platform").mac_ver()[0]
        parts = tuple(int(x) for x in text.split(".") if x.isdigit())
        return parts or None
    except Exception:
        return None


def mac_too_old(read=None) -> bool:
    version = mac_version(read)
    return bool(version) and version < MAC_MINIMUM


def check_window_support() -> bool:
    """Packaged builds: the window needs a modern engine. On Windows that is WebView2, on a Mac it is the one built
    into macOS 13.3 or later. Say so plainly instead of showing a blank 'this page needs JavaScript' window."""
    if sys.platform == "darwin" and mac_too_old():
        show_error("MiniBook Studio needs a newer macOS",
                   "MiniBook Studio shows its window with the web engine built into macOS, and the version on this "
                   f"Mac is too old. It needs macOS {MAC_MINIMUM[0]}.{MAC_MINIMUM[1]} (Ventura) or later.\n\n"
                   "Updating macOS fixes this. Nothing else needs changing.")
        return False
    if sys.platform != "win32" or webview2_installed():
        return True
    show_error("MiniBook Studio needs one more thing",
               "MiniBook Studio shows its window with Microsoft Edge WebView2, which is built into Windows 11 and "
               "current Windows 10 but was not found on this computer.\n\nPress OK to open the download page. "
               "Install the 'Evergreen' runtime, then start MiniBook Studio again.")
    try:
        webbrowser.open(WEBVIEW2_URL)
    except Exception:
        pass
    return False


def is_packaged() -> bool:
    """True for a download (a PyInstaller build, or the Linux .deb whose launcher sets MINIBOOK_PACKAGED)."""
    return is_frozen() or os.environ.get("MINIBOOK_PACKAGED") == "1"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def prepare_environment() -> None:
    """Settings every packaged build needs before the window starts."""
    if sys.platform.startswith("linux"):
        # Qt's web engine refuses to start when the system forbids its sandbox (Ubuntu 24.04 and newer, many
        # containers). The window only ever shows this app's own page on this computer, so run without it.
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
        # The packaged app carries Qt, not GTK: say so, so pywebview does not try GTK first and report an error.
        if is_packaged():
            os.environ.setdefault("PYWEBVIEW_GUI", "qt")
            # This app's page is plain text and pictures; software drawing avoids graphics-driver trouble that can
            # leave the window blank or unopened on some Linux machines.
            flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
            if "--disable-gpu" not in flags:
                os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
            os.environ.setdefault("QT_API", "pyqt6")

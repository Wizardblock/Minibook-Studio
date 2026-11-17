# PyInstaller recipe for MiniBook Studio. Run from the project root:  pyinstaller packaging/minibook.spec
# It makes a folder (not a single file) so the app starts fast and antivirus programs complain less.
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)
sys.path.insert(0, ROOT)
from minibook.about import VERSION  # noqa: E402

datas, binaries, hiddenimports = [], [], []
for package in ("nicegui", "webview"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
if sys.platform.startswith("linux"):
    # pywebview loads its Qt window code and qtpy dynamically, so PyInstaller cannot see them on its own
    for package in ("qtpy", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineCore", "PyQt6.QtWebChannel"):
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    hiddenimports += ["webview.platforms.qt", "PyQt6.QtNetwork", "PyQt6.QtPrintSupport"]
for package in ("uvicorn", "engineio", "socketio", "fastapi", "starlette", "websockets", "h11", "multipart"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass            # a package this build does not have: the self-test in the workflow will say if it mattered
datas += [(os.path.join(ROOT, "assets"), "assets")]          # the bundled font and the icon

if sys.platform == "win32":
    icon = os.path.join(ROOT, "assets", "icon.ico")
elif sys.platform == "darwin":
    icon = os.path.join(ROOT, "assets", "icon.icns")
else:
    icon = None

a = Analysis([os.path.join(ROOT, "minibook_gui.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, noarchive=False)
if sys.platform.startswith("linux"):
    # These were built on Ubuntu 22.04. Bundled copies shadow the newer ones on a newer desktop (Mint 22, Ubuntu 24.04),
    # and then the system's own graphics and file-dialog modules fail to load ("undefined symbol g_task_set_static_name",
    # "Could not initialize GLX"). Use the system's copies: every Linux desktop has them (the .deb depends on them).
    SYSTEM_LIBS = ("libglib-2.0", "libgio-2.0", "libgobject-2.0", "libgmodule-2.0", "libgthread-2.0",
                   "libstdc++", "libgcc_s", "libGL.", "libGLX", "libGLdispatch", "libEGL", "libdrm", "libgbm")
    a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).startswith(SYSTEM_LIBS)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MiniBookStudio", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="MiniBookStudio")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="MiniBook Studio.app", icon=icon,
                 bundle_identifier="io.github.wizardblock.minibookstudio",
                 info_plist={"CFBundleName": "MiniBook Studio", "CFBundleShortVersionString": VERSION,
                             "CFBundleVersion": VERSION, "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "13.3"})      # older macOS lacks the web engine features NiceGUI needs

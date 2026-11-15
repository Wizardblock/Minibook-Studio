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
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MiniBookStudio", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="MiniBookStudio")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="MiniBook Studio.app", icon=icon,
                 bundle_identifier="io.github.wizardblock.minibookstudio",
                 info_plist={"CFBundleName": "MiniBook Studio", "CFBundleShortVersionString": VERSION,
                             "CFBundleVersion": VERSION, "NSHighResolutionCapable": True})

"""`minibook_gui --selftest`: checks a built download has everything it needs, without opening a window (PKG-03)."""
from __future__ import annotations

import importlib
import tempfile
from pathlib import Path


def run() -> list[str]:
    """Run each check; returns the problems found (empty = all good)."""
    problems: list[str] = []

    def check(name, fn):
        try:
            fn()
        except Exception as e:           # report every failure, not just the first
            problems.append(f"{name}: {type(e).__name__}: {e}")

    def fonts():
        from . import spine
        for bold in (True, False):
            if not Path(spine.font_path(bold)).exists():
                raise FileNotFoundError("bundled font missing")

    def libraries():
        for mod in ("PIL", "reportlab", "requests", "platformdirs", "nicegui"):
            importlib.import_module(mod)

    def wrap_and_pdf():
        from PIL import Image
        from . import csvimport as c, net, pdfexport, settings as S, svgexport, testprint
        st = S.Settings()
        n = net.build_net(c.Book("Self Test", ["A. Person"], rating=4.5), Image.new("RGB", (300, 450), (40, 90, 60)), st)
        with tempfile.TemporaryDirectory() as d:
            pdfexport.export_pdf([n], st, Path(d) / "a.pdf")
            svgexport.export_svg([n], st, Path(d) / "a.svg")
            testprint.export_test_print(st, n, Path(d) / "t.pdf")
            for name in ("a.pdf", "a.svg", "t.pdf"):
                if not (Path(d) / name).stat().st_size:
                    raise RuntimeError(f"{name} is empty")

    def sample_workspace():
        from PIL import Image
        from . import controller as ctl_mod, settings as S
        with tempfile.TemporaryDirectory() as d:
            ctl = ctl_mod.AppController(S.Settings(), {}, None, persist=False, custom_dir=Path(d) / "c")
            ctl.load_csv(b"Title,Authors,Read Status,Last Date Read\nOne,A,read,2026/01/01\n", "x.csv")
            ctl.state(ctl.all_books[0]).image = Image.new("RGB", (300, 450))
            ctl.open_workspace(ctl.save_workspace())
            if len(ctl.all_books) != 1:
                raise RuntimeError("workspace round trip failed")

    check("fonts", fonts)
    check("libraries", libraries)
    check("wraps, PDF and SVG", wrap_and_pdf)
    check("workspace", sample_workspace)
    return problems


def window_problems(timeout_s: int = 40) -> list[str]:
    """Linux: open a real pywebview window (Qt, no screen) and load a page, so a download that cannot show its
    window is caught by the build rather than by a user (--selftest-window)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.environ.setdefault("PYWEBVIEW_GUI", "qt")
    os.environ.setdefault("QT_API", "pyqt6")
    try:
        import webview
    except Exception as e:
        return [f"window: pywebview is missing: {type(e).__name__}: {e}"]
    result: list[str] = []
    window = webview.create_window("MiniBook Studio self-test", html="<html><body><p>MiniBook Studio</p></body></html>")

    def check() -> None:
        if not window.events.loaded.wait(timeout_s):
            result.append("window: the window opened but its page did not load in time")
        window.destroy()

    watchdog = threading.Timer(timeout_s + 10, lambda: os._exit(1))
    watchdog.daemon = True
    watchdog.start()
    try:
        webview.start(check, gui="qt")
    except Exception as e:
        result.append(f"window: pywebview could not start its Qt window: {type(e).__name__}: {e}")
    watchdog.cancel()
    return result

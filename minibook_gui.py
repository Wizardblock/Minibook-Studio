"""Launcher. Run:  python minibook_gui.py   (add --browser to use your web browser instead of a window)

The `__mp_main__` check is required by NiceGUI's native window mode, which re-imports this file
in a helper process. `freeze_support` is needed once the app is packaged into a download.
"""
import multiprocessing
import os
import sys

_QUIET_FLAGS = ("--selftest", "--selftest-window", "--version", "--help", "-h")
if (getattr(sys, "frozen", False) or os.environ.get("MINIBOOK_PACKAGED") == "1") and not (set(sys.argv) & set(_QUIET_FLAGS)):
    # a packaged app has no console: keep what it prints in a log file (the check flags still print to the terminal)
    from minibook import fatal

    if fatal.redirect_output_to_log() is None and sys.stdout is None:
        sys.stdout = sys.stderr = open(os.devnull, "w")
elif sys.stdout is None:
    sys.stdout = sys.stderr = open(os.devnull, "w")

from minibook.gui import main  # noqa: E402

if __name__ in {"__main__", "__mp_main__"}:
    multiprocessing.freeze_support()
    main()

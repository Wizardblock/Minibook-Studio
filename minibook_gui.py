"""Launcher. Run:  python minibook_gui.py   (add --browser to use your web browser instead of a window)

The `__mp_main__` check is required by NiceGUI's native window mode, which re-imports this file
in a helper process. `freeze_support` is needed once the app is packaged into a download.
"""
import multiprocessing
import os
import sys

if sys.stdout is None:      # a windowed (no console) build has no output streams; libraries still write to them
    sys.stdout = sys.stderr = open(os.devnull, "w")

from minibook.gui import main  # noqa: E402

if __name__ in {"__main__", "__mp_main__"}:
    multiprocessing.freeze_support()
    main()

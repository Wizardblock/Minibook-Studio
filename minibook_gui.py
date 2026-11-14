"""Launcher. Run:  python minibook_gui.py   (add --browser to use your web browser instead of a window)

The `__mp_main__` check is required by NiceGUI's native window mode, which re-imports this file
in a helper process.
"""
from minibook.gui import main

if __name__ in {"__main__", "__mp_main__"}:
    main()

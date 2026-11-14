"""What the About window says (ABOUT-01). Kept apart from the GUI so it can be tested and reused."""
from __future__ import annotations

VERSION = "0.1.0"
APP_NAME = "MiniBook Studio"
TAGLINE = "Turn your reading list into tiny books."
REPO_URL = "https://github.com/Wizardblock/Minibook-Studio"
LICENSE_NAME = "MIT licence"
NOT_AFFILIATED = ("MiniBook Studio is an independent project. It is not made by, or affiliated with, "
                  "StoryGraph, Goodreads or Amazon.")
PRIVACY = ("Your books and settings stay on this computer. To find covers the app contacts Open Library, "
           "Google Books and Amazon's public image server, sending only a title, author or ISBN. "
           "The optional Google key is stored in a plain text settings file on this computer.")
CREDITS = (
    ("Covers and editions", "Open Library (openlibrary.org) and Google Books"),
    ("Font", "DejaVu Sans Condensed, free licence from Bitstream and the DejaVu authors"),
    ("Built with", "Python, NiceGUI, Pillow, ReportLab"),
)


def version_line() -> str:
    return f"{APP_NAME} {VERSION}"

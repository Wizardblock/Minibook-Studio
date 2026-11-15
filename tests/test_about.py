"""ABOUT-01: the About window and the version number."""
import re
import unittest
from types import SimpleNamespace

from minibook import about
import minibook
from tests import fake_nicegui as fake
from tests.test_gui_wiring import GuiBase


class TestAboutText(unittest.TestCase):
    def test_ABOUT01_the_version_looks_like_a_version_and_is_shared(self):
        self.assertRegex(about.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(minibook.__version__, about.VERSION)
        self.assertEqual(about.version_line(), f"MiniBook Studio {about.VERSION}")

    def test_ABOUT01_it_says_who_it_is_not_and_where_the_data_goes(self):
        for name in ("StoryGraph", "Goodreads", "Amazon"):
            self.assertIn(name, about.NOT_AFFILIATED)
        for site in ("Open Library", "Google Books", "Amazon"):
            self.assertIn(site, about.PRIVACY)
        self.assertIn("plain text", about.PRIVACY)

    def test_ABOUT01_the_repo_link_is_the_project_page(self):
        self.assertTrue(about.REPO_URL.startswith("https://github.com/Wizardblock/"))


class TestAboutWindow(GuiBase):
    def test_ABOUT01_the_header_has_an_about_button_that_opens_the_window(self):
        btn = [b for b in fake.find("button") if b.kwargs.get("icon") == "info"]
        self.assertEqual(len(btn), 1)
        self.assertFalse(any(n == "open" for d in fake.find("dialog") for n, _a, _k in d.calls))
        btn[0].kwargs["on_click"]()
        opened = [d for d in fake.find("dialog") if any(n == "open" for n, _a, _k in d.calls)]
        self.assertEqual(len(opened), 1)

    def test_ABOUT01_the_window_shows_version_licence_credits_and_the_link(self):
        texts = [e.text for e in fake.find("label")]
        self.assertIn(f"Version {about.VERSION}", texts)
        self.assertTrue(any("MIT licence" in t for t in texts))
        self.assertTrue(any("not made by, or affiliated with" in t for t in texts))
        self.assertTrue(any("DejaVu" in t for t in texts))
        self.assertTrue(any("Open Library" in t for t in texts))
        link = fake.find("link")[0]
        self.assertEqual(link.args[1], about.REPO_URL)
        self.assertTrue(link.kwargs.get("new_tab"))

    def test_ABOUT01_the_window_has_a_close_button(self):
        close = fake.find("button", text="Close")
        self.assertTrue(close)


if __name__ == "__main__":
    unittest.main()

"""SYS-02: the engine runs from a command line, with no GUI."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pdfplumber

from tests.helpers import REAL_CSV, ROOT


def run(*args, home):
    env = dict(os.environ, XDG_CONFIG_HOME=str(home / "cfg"), XDG_CACHE_HOME=str(home / "cache"), HOME=str(home))
    return subprocess.run([sys.executable, "-m", "minibook", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def test_SYS02_offline_build_writes_a_pdf(self):
        out = self.home / "w.pdf"
        r = run("build", "--csv", str(REAL_CSV), "--year", "2026", "--offline", "--out", str(out), home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("35 books", r.stdout)
        with pdfplumber.open(out) as pdf:
            self.assertEqual(len(pdf.pages[0].images), 28)      # 4 x 7 per page at 1.75 x 1.25 in

    def test_SYS02_no_matching_books_is_a_clear_error(self):
        r = run("build", "--csv", str(REAL_CSV), "--year", "1850", "--offline", "--out", str(self.home / "x.pdf"), home=self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("No books matched", r.stderr)

    def test_SYS02_wrong_file_is_a_clear_error(self):
        bad = self.home / "bad.csv"
        bad.write_text("a,b\n1,2\n")
        r = run("build", "--csv", str(bad), "--offline", home=self.home)
        self.assertEqual(r.returncode, 2)
        self.assertIn("StoryGraph", r.stderr)

    def test_IMG10_unreachable_network_does_not_crash_the_build(self):
        # Sandbox has no route to the cover sites, which is exactly the offline failure case.
        out = self.home / "n.pdf"
        r = run("build", "--csv", str(REAL_CSV), "--year", "2025", "--out", str(out), home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()

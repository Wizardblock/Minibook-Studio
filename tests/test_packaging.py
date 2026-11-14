"""PKG-01..PKG-06: what we can check about the packaged downloads without building them."""
import io
import py_compile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml
from PIL import Image

from minibook import about, spine
from tests import fake_nicegui as fake

ROOT = Path(__file__).resolve().parent.parent


class TestSelfTest(unittest.TestCase):
    def setUp(self):
        fake.install()
        from minibook import selftest
        self.selftest = selftest

    def test_PKG03_a_good_install_passes(self):
        self.assertEqual(self.selftest.run(), [])

    def test_PKG03_a_missing_font_is_reported(self):
        original = spine.font_path
        spine.font_path = lambda bold=True: "/nowhere/font.ttf"
        try:
            problems = self.selftest.run()
        finally:
            spine.font_path = original
        self.assertTrue(any(p.startswith("fonts") for p in problems), problems)
        self.assertTrue(any(p.startswith("wraps") for p in problems), problems)

    def test_PKG03_a_missing_library_is_reported_and_the_others_still_run(self):
        import sys
        saved = sys.modules.pop("nicegui")
        sys.modules["nicegui"] = None                       # makes `import nicegui` fail
        try:
            problems = self.selftest.run()
        finally:
            sys.modules["nicegui"] = saved
        self.assertEqual([p.split(":")[0] for p in problems], ["libraries"])

    def test_PKG03_the_command_line_flags_print_and_exit(self):
        from minibook import gui
        out = io.StringIO()
        with redirect_stdout(out):
            gui.main(["--version"])
        self.assertEqual(out.getvalue().strip(), about.version_line())
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            gui.main(["--selftest"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("self-test passed", out.getvalue())

    def test_PKG03_selftest_can_write_its_result_to_a_file_for_windowed_builds(self):
        from minibook import gui
        log = Path(tempfile.mkdtemp()) / "r.log"
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            gui.main(["--selftest", "--log", str(log)])
        self.assertIn("self-test passed", log.read_text())

    def test_PKG03_a_failing_selftest_exits_nonzero(self):
        from minibook import gui, selftest
        original = selftest.run
        selftest.run = lambda: ["fonts: broken"]
        try:
            with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as cm:
                gui.main(["--selftest"])
        finally:
            selftest.run = original
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("FAILED", out.getvalue())


class TestIconsAndRecipe(unittest.TestCase):
    def test_PKG01_icons_exist_in_every_format(self):
        png = Image.open(ROOT / "assets" / "icon.png")
        self.assertEqual(png.size, (512, 512))
        ico = Image.open(ROOT / "assets" / "icon.ico")
        self.assertIn((256, 256), ico.info.get("sizes", {(256, 256)}))
        icns = (ROOT / "assets" / "icon.icns").read_bytes()
        self.assertEqual(icns[:4], b"icns")

    def test_PKG01_the_recipe_is_valid_python_and_names_the_launcher_and_assets(self):
        spec = ROOT / "packaging" / "minibook.spec"
        py_compile.compile(str(spec), cfile=str(Path(tempfile.mkdtemp()) / "x.pyc"), doraise=True)
        text = spec.read_text()
        self.assertIn("minibook_gui.py", text)
        self.assertIn('"assets"', text)
        self.assertIn("MiniBookStudio", text)
        self.assertIn("console=False", text)

    def test_PKG02_the_launcher_supports_frozen_apps(self):
        text = (ROOT / "minibook_gui.py").read_text()
        self.assertIn("freeze_support", text)
        self.assertIn("sys.stdout is None", text)

    def test_PKG02_the_font_lookup_knows_about_pyinstaller(self):
        self.assertIn("_MEIPASS", Path(spine.__file__).read_text())


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.wf = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text())

    def test_PKG04_it_builds_all_three_systems_after_the_tests_pass(self):
        build = self.wf["jobs"]["build"]
        self.assertEqual(build["needs"], "test")
        systems = {m["name"] for m in build["strategy"]["matrix"]["include"]}
        self.assertEqual(systems, {"windows", "macos", "linux"})
        self.assertFalse(build["strategy"]["fail-fast"])             # one failing system must not hide the others

    def test_PKG04_every_system_is_self_tested_and_uploaded(self):
        steps = self.wf["jobs"]["build"]["steps"]
        names = [s.get("name", "") for s in steps]
        for system in ("Windows", "Mac", "Linux"):
            self.assertTrue(any(n.startswith("Self-test") and system in n for n in names), system)
        self.assertTrue(any("upload-artifact" in s.get("uses", "") for s in steps))

    def test_PKG05_a_release_is_made_only_for_version_tags_and_has_checksums(self):
        rel = self.wf["jobs"]["release"]
        self.assertIn("refs/tags/v", rel["if"])
        self.assertEqual(rel["permissions"], {"contents": "write"})
        self.assertIn("SHA256SUMS", yaml.dump(rel))
        self.assertEqual(self.wf["permissions"], {"contents": "read"})     # read-only everywhere else

    def test_PKG05_pull_requests_run_the_tests_and_builds_but_never_release(self):
        triggers = self.wf[True]
        self.assertIn("pull_request", triggers)
        self.assertIn("v*", triggers["push"]["tags"])


class TestStage(unittest.TestCase):
    def fake_dist(self, os_name):
        d = Path(tempfile.mkdtemp())
        if os_name == "windows":
            (d / "MiniBookStudio").mkdir()
            (d / "MiniBookStudio" / "MiniBookStudio.exe").write_text("x")
        elif os_name == "macos":
            (d / "MiniBook Studio.app" / "Contents").mkdir(parents=True)
            (d / "MiniBook Studio.app" / "Contents" / "Info.plist").write_text("x")
        else:
            (d / "MiniBook-Studio-x86_64.AppImage").write_text("x")
        return d

    def stage(self, os_name):
        import importlib.util
        spec = importlib.util.spec_from_file_location("stage", ROOT / "packaging" / "stage.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out = Path(tempfile.mkdtemp())
        return mod.stage(os_name, self.fake_dist(os_name), out, "1.2.3")

    def test_PKG06_every_download_has_the_app_the_sample_the_licence_and_the_notes(self):
        for os_name, expected in (("windows", "MiniBook Studio/MiniBookStudio.exe"),
                                  ("macos", "MiniBook Studio.app/Contents/Info.plist"),
                                  ("linux", "MiniBook-Studio-x86_64.AppImage")):
            folder = self.stage(os_name)
            self.assertEqual(folder.name, f"MiniBook-Studio-{os_name}-1.2.3")
            self.assertTrue((folder / expected).exists(), os_name)
            self.assertTrue((folder / "samples" / "sample_library.csv").exists())
            self.assertTrue((folder / "LICENSE").exists())
            notes = (folder / "READ ME FIRST.txt").read_text()
            self.assertIn("1.2.3", notes)
            self.assertNotIn("{version}", notes)

    def test_PKG06_the_notes_explain_the_unsigned_warning_for_each_system(self):
        self.assertIn("More info", self.stage("windows").joinpath("READ ME FIRST.txt").read_text())
        self.assertIn("Open Anyway", self.stage("macos").joinpath("READ ME FIRST.txt").read_text())
        self.assertIn("chmod +x", self.stage("linux").joinpath("READ ME FIRST.txt").read_text())

    def test_PKG06_an_unknown_system_is_refused(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("stage2", ROOT / "packaging" / "stage.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with self.assertRaises(ValueError):
            mod.stage("beos", Path("."), Path(tempfile.mkdtemp()), "1")


if __name__ == "__main__":
    unittest.main()

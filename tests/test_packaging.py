"""PKG-01..PKG-06: what we can check about the packaged downloads without building them."""
import io
import py_compile
import shutil
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
        self.assertIn("MINIBOOK_PACKAGED", text)
        self.assertIn("freeze_support", text)
        self.assertIn("sys.stdout is None", text)

    def test_PKG02_the_font_lookup_knows_about_pyinstaller(self):
        self.assertIn("_MEIPASS", Path(spine.__file__).read_text())


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.wf = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text())

    def test_PKG04_windows_and_mac_are_built_and_linux_is_a_package_tested_on_two_ubuntus(self):
        build = self.wf["jobs"]["build"]
        self.assertEqual(build["needs"], "test")
        systems = {m["name"] for m in build["strategy"]["matrix"]["include"]}
        self.assertEqual(systems, {"windows", "macos"})
        self.assertFalse(build["strategy"]["fail-fast"])             # one failing system must not hide the others
        self.assertEqual(self.wf["jobs"]["linux"]["needs"], "test")
        test = self.wf["jobs"]["linux-test"]
        self.assertEqual(test["needs"], "linux")
        self.assertEqual(set(test["strategy"]["matrix"]["os"]), {"ubuntu-22.04", "ubuntu-24.04"})
        self.assertEqual(set(self.wf["jobs"]["release"]["needs"]), {"build", "linux-test", "generic-test"})

    def test_PKG04_the_generic_linux_download_is_started_in_several_distributions(self):
        gen = self.wf["jobs"]["generic-test"]
        images = set(gen["strategy"]["matrix"]["image"])
        self.assertTrue({"ubuntu:24.04", "debian:12", "fedora:latest", "archlinux:latest"} <= images, images)
        text = yaml.dump(self.wf["jobs"]["appimage"])
        self.assertIn("libglib-2.0", text)                      # the bundle must not carry the system's own libraries

    def test_PKG04_every_system_is_self_tested_and_uploaded(self):
        steps = self.wf["jobs"]["build"]["steps"]
        names = [s.get("name", "") for s in steps]
        for system in ("Windows", "Mac"):
            self.assertTrue(any(n.startswith("Self-test") and system in n for n in names), system)
        self.assertTrue(any("Install and self-test the installer" in n for n in names))
        self.assertTrue(any("upload-artifact" in s.get("uses", "") for s in steps))
        linux_text = yaml.dump(self.wf["jobs"]["linux-test"])
        for needle in ("--selftest-window", "xdotool", "apt-get install -y ./pkg/"):
            self.assertIn(needle, linux_text)

    def test_PKG04_the_actions_are_on_node24_releases_and_appstream_is_installed(self):
        text = (ROOT / ".github" / "workflows" / "build.yml").read_text()
        for old in ("upload-artifact@v4", "upload-artifact@v5", "download-artifact@v4",
                    "download-artifact@v5", "checkout@v4", "setup-python@v5"):
            self.assertNotIn(old, text)
        self.assertIn("apt-get install -y appstream", text)

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
                                  ("macos", "MiniBook Studio.app/Contents/Info.plist")):
            folder = self.stage(os_name)
            want = {"windows": "MiniBook-Studio-windows-portable-1.2.3",
                    "macos": "MiniBook-Studio-macos-1.2.3"}[os_name]
            self.assertEqual(folder.name, want)
            self.assertTrue((folder / expected).exists(), os_name)
            self.assertTrue((folder / "samples" / "sample_library.csv").exists())
            self.assertTrue((folder / "LICENSE").exists())
            notes = (folder / "READ ME FIRST.txt").read_text()
            self.assertIn("1.2.3", notes)
            self.assertNotIn("{version}", notes)

    def test_PKG06_the_notes_explain_the_unsigned_warning_for_each_system(self):
        self.assertIn("More info", self.stage("windows").joinpath("READ ME FIRST.txt").read_text())
        self.assertIn("Open Anyway", self.stage("macos").joinpath("READ ME FIRST.txt").read_text())

    def test_PKG06_linux_has_no_staged_folder_because_it_ships_as_deb_and_appimage(self):
        with self.assertRaises(ValueError):
            self.stage("linux")

    def test_PKG06_an_unknown_system_is_refused(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("stage2", ROOT / "packaging" / "stage.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with self.assertRaises(ValueError):
            mod.stage("beos", Path("."), Path(tempfile.mkdtemp()), "1")


class TestInstallers(unittest.TestCase):
    def test_PKG07_linux_metadata_is_valid_xml_with_matching_ids(self):
        import xml.etree.ElementTree as ET
        d = ROOT / "packaging" / "linux"
        meta = next(d.glob("*.metainfo.xml"))
        desktop = next(d.glob("*.desktop"))
        root = ET.parse(meta).getroot()
        app_id = root.findtext("id")
        self.assertEqual(app_id, "io.github.wizardblock.minibookstudio")
        self.assertEqual(meta.name, app_id + ".metainfo.xml")
        self.assertEqual(desktop.name, app_id + ".desktop")
        self.assertIn("Exec=", desktop.read_text())

    def test_PKG07_the_deb_uses_the_systems_python_and_qt_and_sets_up_a_private_folder(self):
        text = (ROOT / "packaging" / "make_deb.sh").read_text()
        for needle in ("Depends:", "python3-pyqt6", "python3-pyqt6.qtwebengine", "dpkg-deb", "metainfo", "Architecture: all"):
            self.assertIn(needle, text)
        post = (ROOT / "packaging" / "linux" / "postinst").read_text()
        self.assertIn("--system-site-packages", post)
        self.assertIn("pip install", post)
        self.assertIn("rm -rf", (ROOT / "packaging" / "linux" / "postrm").read_text())
        launcher = (ROOT / "packaging" / "linux" / "minibook-studio").read_text()
        self.assertIn("MINIBOOK_PACKAGED=1", launcher)
        self.assertIn("venv/bin/python", launcher)

    @unittest.skipUnless(shutil.which("dpkg-deb") and shutil.which("bash"), "needs dpkg-deb")
    def test_PKG07_the_deb_builds_and_holds_the_app_launcher_and_metadata(self):
        import subprocess
        subprocess.run(["bash", str(ROOT / "packaging" / "make_deb.sh"), "9.9.9"], cwd=ROOT, check=True,
                       capture_output=True)
        deb = ROOT / "dist" / "minibook-studio_9.9.9_all.deb"
        try:
            listing = subprocess.run(["dpkg-deb", "-c", str(deb)], check=True, capture_output=True, text=True).stdout
            for expected in ("opt/minibook-studio/app/minibook_gui.py", "opt/minibook-studio/app/minibook/gui.py",
                             "opt/minibook-studio/app/assets/fonts/DejaVuSansCondensed-Bold.ttf",
                             "usr/bin/minibook-studio", "opt/minibook-studio/requirements.txt",
                             "io.github.wizardblock.minibookstudio.desktop",
                             "io.github.wizardblock.minibookstudio.metainfo.xml"):
                self.assertIn(expected, listing)
            reqs = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(deb)], check=True, capture_output=True).stdout
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(reqs)) as tar:
                text = tar.extractfile("./opt/minibook-studio/requirements.txt").read().decode()
            self.assertIn("nicegui", text)
            self.assertIn("pywebview", text)
            self.assertNotIn("pdfplumber", text)               # tests only
            self.assertNotIn("PyQt6", text)                    # comes from the system
        finally:
            deb.unlink(missing_ok=True)

    def test_PKG07_the_appimage_leaves_system_libraries_to_the_system(self):
        spec = (ROOT / "packaging" / "minibook.spec").read_text()
        for lib in ("libglib-2.0", "libgio-2.0", "libstdc++", "libGL", "libEGL"):
            self.assertIn(lib, spec)
        self.assertIn("qtpy", spec)
        script = (ROOT / "packaging" / "make_appimage.sh").read_text()
        self.assertIn("VERSION", script)
        self.assertIn("metainfo", script)
        gen = (ROOT / "packaging" / "linux" / "test-generic.sh").read_text()
        for distro_tool in ("apt-get", "dnf", "pacman"):
            self.assertIn(distro_tool, gen)

    def test_PKG07_the_windows_installer_is_per_user_and_named_by_version(self):
        text = (ROOT / "packaging" / "installer.iss").read_text()
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn("MiniBook-Studio-Setup-{#Version}", text)

    def test_PKG07_release_notes_have_version_placeholders(self):
        text = (ROOT / "packaging" / "release-notes.md").read_text()
        self.assertIn("{version}", text)


class TestFatal(unittest.TestCase):
    def test_PKG08_webview2_detection_reads_the_registry_through_an_injectable_reader(self):
        from minibook import fatal
        self.assertTrue(fatal.webview2_installed(lambda *a: "120.0.1"))
        self.assertFalse(fatal.webview2_installed(lambda *a: None))

    def test_PKG08_logging_goes_to_a_file_in_the_cache_folder(self):
        from minibook import fatal
        self.assertEqual(fatal.log_path().name, "minibook.log")

    def test_PKG08_selftest_window_implies_selftest(self):
        fake.install()
        from minibook import gui, selftest
        orig = selftest.window_problems
        selftest.window_problems = lambda timeout_s=40, log=None: []
        try:
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
                gui.main(["--selftest-window"])
        finally:
            selftest.window_problems = orig
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("self-test passed", out.getvalue())


if __name__ == "__main__":
    unittest.main()

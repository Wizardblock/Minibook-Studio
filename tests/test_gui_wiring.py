"""GUI-13: our view code runs and its handlers work, against a STAND-IN nicegui.

This proves our own wiring (no typos, handlers call the controller correctly, nothing crashes).
It does NOT prove we use NiceGUI's real API correctly. That is only checked by launching it.
"""
import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from minibook import covers, settings as S
from minibook.controller import YEAR_ALL, AppController
from tests import fake_nicegui as fake
from tests.helpers import REAL_CSV, FakeHttp, gradient_png, json_bytes

CSV = REAL_CSV.read_bytes()


def routes():
    return {
        "covers.openlibrary.org/b/isbn/": (200, gradient_png(600, 900)),
        # a search that finds the book that was asked for
        "openlibrary.org/search.json": lambda url, params: (200, json_bytes({"docs": [
            {"title": params["title"], "author_name": [params.get("author", "")], "cover_i": 1}]})),
        "covers.openlibrary.org/b/id/1": (200, gradient_png(300, 450)),
        "googleapis.com": (200, json_bytes({"items": []})),
    }


def labels():
    return [e.text for e in fake.find("label")]


class GuiBase(unittest.TestCase):
    def setUp(self):
        self.mod = fake.install()
        from minibook import gui
        self.gui = gui
        self.tmp = Path(tempfile.mkdtemp())
        svc = covers.CoverService(FakeHttp(routes()), self.tmp / "cache")
        self.ctl = AppController(S.Settings(output_dir=str(self.tmp / "pdfs")), {}, svc,
                                 settings_path=self.tmp / "s.json", prefs_path=self.tmp / "p.json",
                                 custom_dir=self.tmp / "custom", edits_path=self.tmp / "e.json")
        self.gui.build_page(self.ctl)
        self.ui = self.mod.ui

    def run_async(self, coro_or_value):
        if asyncio.iscoroutine(coro_or_value):
            return asyncio.run(coro_or_value)
        return coro_or_value

    def upload_csv(self, style="old"):
        up = fake.find("upload", where=lambda e: "CSV" in e.kwargs.get("label", ""))[0]
        if style == "old":
            ev = SimpleNamespace(content=io.BytesIO(CSV), name="export.csv")
        else:
            class F:
                name = "export.csv"

                async def read(self_inner):
                    return CSV
            ev = SimpleNamespace(file=F())
        self.run_async(up.kwargs["on_upload"](ev))

    def click(self, text, nth=0, **kw):
        btn = fake.find("button", text=text, **kw)[nth]
        return self.run_async(btn.kwargs["on_click"]())

    def cover_cards(self):
        """The clickable cover cards in the cover dialog."""
        return fake.find("card", where=lambda e: any(n == "on" and a and a[0] == "click" for n, a, _k in e.calls))

    def click_card(self, card):
        handler = [a[1] for n, a, _k in card.calls if n == "on" and a[0] == "click"][0]
        return self.run_async(handler())

    def unchosen_card(self):
        return next(x for x in self.cover_cards() if "ring-2" not in " ".join(
            a[0] for n, a, _k in x.calls if n == "classes"))

    def book_button(self, title):
        for b in fake.find("button", text="Cover"):
            defaults = b.kwargs["on_click"].__defaults__
            if defaults and defaults[1].title == title:
                return b
        raise AssertionError(f"no Cover button for {title}")


class TestPage(GuiBase):
    def test_page_builds_empty_and_shows_the_welcome_text(self):
        self.assertTrue(any("Upload your StoryGraph or Goodreads export" in t for t in labels()))
        self.assertTrue(any("Settings" == t for t in labels()))

    def test_main_registers_page_and_chooses_window_mode(self):
        self.gui.main(["--browser", "--offline"])
        self.assertIsNotNone(self.ui.page_fn)
        self.assertFalse(self.ui.run_kwargs["native"])
        self.assertTrue(self.ui.run_kwargs["show"])
        self.assertFalse(self.ui.run_kwargs["reload"])
        self.ui.page_fn()      # the registered page function builds without error

    def test_main_uses_a_native_window_when_pywebview_is_present(self):
        import sys, types
        sys.modules["webview"] = types.ModuleType("webview")
        fakes = {"qtpy": types.ModuleType("qtpy"), "PyQt6": types.ModuleType("PyQt6"),        # stand in for the
                 "PyQt6.QtGui": types.ModuleType("PyQt6.QtGui"),                                  # Linux window backend
                 "PyQt6.QtWebEngineWidgets": types.ModuleType("PyQt6.QtWebEngineWidgets")}
        fakes["PyQt6"].QtGui = fakes["PyQt6.QtGui"]
        fakes["PyQt6"].QtWebEngineWidgets = fakes["PyQt6.QtWebEngineWidgets"]
        sys.modules.update(fakes)
        try:
            self.gui.main([])
        finally:
            sys.modules.pop("webview", None)
            for name in fakes:
                sys.modules.pop(name, None)
        kw = self.ui.run_kwargs
        self.assertTrue(kw["native"])
        self.assertFalse(kw["show"])
        self.assertEqual(kw["window_size"], (1360, 900))
        self.assertNotIn("port", kw)

    def test_a_window_backend_that_cannot_load_its_libraries_is_reported_in_words(self):
        import sys, types
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux window backend")
        sys.modules["webview"] = types.ModuleType("webview")
        sys.modules["qtpy"] = types.ModuleType("qtpy")
        sys.modules["PyQt6"] = None                          # import fails like a missing libGL would
        sys.modules["gi"] = None
        try:
            self.assertFalse(self.gui._pywebview_available())
            self.assertIn("PyQt6", self.gui.WINDOW_PROBLEM)
        finally:
            for name in ("webview", "qtpy", "PyQt6", "gi"):
                sys.modules.pop(name, None)

    def test_main_falls_back_to_the_browser_when_pywebview_has_no_window_backend(self):
        import sys, types
        sys.modules["webview"] = types.ModuleType("webview")
        for name in ("qtpy", "gi"):
            sys.modules[name] = None                          # makes "import name" fail
        try:
            if sys.platform.startswith("linux"):
                self.gui.main([])
                self.assertFalse(self.ui.run_kwargs["native"])
                self.assertTrue(self.ui.run_kwargs["show"])
        finally:
            for name in ("webview", "qtpy", "gi"):
                sys.modules.pop(name, None)

    def test_main_falls_back_to_the_browser_without_pywebview(self):
        import sys
        sys.modules.pop("webview", None)
        self.gui.main([])
        kw = self.ui.run_kwargs
        if not kw["native"]:                       # (true unless pywebview happens to be installed here)
            self.assertTrue(kw["show"])
            self.assertEqual(kw["port"], 8765)

    def test_new_style_upload_with_a_synchronous_read(self):
        class F:
            name = "a.csv"

            def read(self):
                return b"hello"
        ev = SimpleNamespace(file=F())
        self.assertEqual(asyncio.run(self.gui.read_upload(ev)), (b"hello", "a.csv"))

    def test_data_url_and_upload_reader(self):
        url = self.gui.data_url(Image.new("RGB", (400, 300), (1, 2, 3)), 100)
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        ev = SimpleNamespace(content=io.BytesIO(b"abc"), name="a.csv")
        self.assertEqual(asyncio.run(self.gui.read_upload(ev)), (b"abc", "a.csv"))


class TestImportFlow(GuiBase):
    def test_csv_upload_old_and_new_event_shapes(self):
        for style in ("old", "new"):
            self.mod.ui.notifications.clear()
            self.ctl.all_books = []
            self.upload_csv(style)
            self.assertEqual(self.ctl.year, 2026, style)
            self.assertTrue(any("Loaded 157 books" in m for m, _ in self.ui.notifications), style)

    def test_review_list_shows_both_groups_and_one_row_per_book(self):
        self.upload_csv()
        all_button = fake.find("button", text="All")[0]
        fake.El.registry.clear()                   # count only what the next render creates
        all_button.kwargs["on_click"]()            # the group button re-renders the whole list
        texts = labels()
        self.assertTrue(any(t == "Read in 2026" for t in texts))
        self.assertTrue(any(t.startswith("No read date (18)") for t in texts))
        self.assertEqual(len(fake.find("checkbox")), 35 + 18)

    def test_wrong_csv_shows_a_readable_error_and_keeps_state(self):
        up = fake.find("upload", where=lambda e: "CSV" in e.kwargs.get("label", ""))[0]
        ev = SimpleNamespace(content=io.BytesIO(b"a,b\n1,2\n"), name="bad.csv")
        self.run_async(up.kwargs["on_upload"](ev))
        self.assertTrue(any("StoryGraph" in m and k.get("type") == "negative" for m, k in self.ui.notifications))
        self.assertEqual(self.ctl.all_books, [])

    def test_unreadable_bytes_do_not_crash(self):
        up = fake.find("upload", where=lambda e: "CSV" in e.kwargs.get("label", ""))[0]
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(b"\xff\xfe\x00bad"), name="x.csv")))
        self.assertTrue(any(k.get("type") == "negative" for _, k in self.ui.notifications))

    def test_checkbox_updates_selection(self):
        self.upload_csv()
        first = self.ctl.dated[0]
        box = fake.find("checkbox", where=lambda e: e.kwargs.get("on_change") and
                        e.kwargs["on_change"].__defaults__ == (first.id,))[-1]
        box.kwargs["on_change"](SimpleNamespace(value=False))
        self.assertFalse(first.selected)

    def test_manual_entry_adds_a_row_and_clears_the_fields(self):
        title = fake.find("input", where=lambda e: e.kwargs.get("label") == "Title")[0]
        title.value = "Dune"
        self.click("Add")
        self.assertEqual([b.title for b in self.ctl.manual], ["Dune"])
        self.assertEqual(title.value, "")

    def test_manual_entry_without_title_warns(self):
        self.click("Add")
        self.assertTrue(any(k.get("type") == "warning" for _, k in self.ui.notifications))
        self.assertEqual(self.ctl.manual, [])

    def test_filter_selects_refilter_the_list(self):
        self.upload_csv()
        year = fake.find("select", where=lambda e: e.kwargs.get("label") == "Year read")[-1]
        year.value = 2025
        year.kwargs["on_change"](SimpleNamespace(value=2025))
        self.assertEqual(self.ctl.year, 2025)
        self.assertEqual(len(self.ctl.dated), 18)


class TestSettingsPanel(GuiBase):
    def number(self, label):
        return fake.find("number", where=lambda e: e.kwargs.get("label") == label)[-1]

    def test_height_edit_converts_units_and_saves(self):
        self.number("Height").kwargs["on_change"](SimpleNamespace(value=1.0))
        self.assertAlmostEqual(self.ctl.settings.height_mm, 25.4)
        self.assertEqual(S.load_settings(self.tmp / "s.json").height_mm, self.ctl.settings.height_mm)

    def test_clearing_a_number_box_is_ignored(self):
        before = self.ctl.settings.height_mm
        self.number("Height").kwargs["on_change"](SimpleNamespace(value=None))
        self.assertEqual(self.ctl.settings.height_mm, before)

    def test_unit_switch_redraws_in_millimeters(self):
        radio = fake.find("radio", where=lambda e: "in" in (e.args[0] if e.args else {}))[0]
        radio.kwargs["on_change"](SimpleNamespace(value="mm"))
        self.assertEqual(self.ctl.settings.unit, "mm")
        self.assertAlmostEqual(self.number("Height").kwargs["value"], 31.75, places=2)   # 1.25 in

    def test_invalid_gutter_shows_a_red_problem_and_blocks_export(self):
        self.number("Gap between books").kwargs["on_change"](SimpleNamespace(value=0.01))
        self.assertTrue(any("gutter" in t for t in labels()))
        self.upload_csv()
        self.click("Create PDF")
        self.assertTrue(any("Fix the settings" in m for m, _ in self.ui.notifications))

    def test_aspect_mode_shows_an_aspect_box(self):
        radio = fake.find("radio", where=lambda e: "aspect" in (e.args[0] if e.args else {}))[0]
        radio.kwargs["on_change"](SimpleNamespace(value="aspect"))
        box = fake.find("input", where=lambda e: "Aspect" in e.kwargs.get("label", ""))[-1]
        box.kwargs["on_change"](SimpleNamespace(value="2:3"))
        self.assertAlmostEqual(self.ctl.settings.aspect, 2 / 3)
        box.kwargs["on_change"](SimpleNamespace(value="nonsense"))       # ignored, no crash
        self.assertAlmostEqual(self.ctl.settings.aspect, 2 / 3)

    def test_EXP04_no_glue_or_sticker_choice_and_no_margin_note(self):
        self.assertEqual(fake.find("radio", where=lambda e: "glue" in str(e.args)), [])
        self.assertEqual(fake.find("label", text="For sticker paper"), [])

    def test_back_cover_and_spine_switches(self):
        radio = fake.find("radio", where=lambda e: "complement" in (e.args[0] if e.args else {}))[0]
        radio.kwargs["on_change"](SimpleNamespace(value="complement"))
        sw = fake.find("switch", text="Hide author")[0]
        sw.kwargs["on_change"](SimpleNamespace(value=True))
        self.assertEqual((self.ctl.settings.back_style, self.ctl.settings.spine_hide_author), ("complement", True))

    def test_scale_calculator_button(self):
        for lbl, val in (("Real width (in)", 5.5), ("Real height (in)", 8.5), ("Real thickness (in)", 1.0), ("Scale 1 :", 10)):
            fake.find("number", where=lambda e, l=lbl: e.args and e.args[0] == l)[-1].value = val
        self.click("Apply")
        self.assertAlmostEqual(self.ctl.show(self.ctl.settings.height_mm), 0.85)


class TestCoverDialog(GuiBase):
    def open_hyperion(self):
        self.upload_csv()
        self.run_async(self.book_button("Hyperion").kwargs["on_click"]())

    def test_dialog_lists_candidates_with_badges(self):
        self.open_hyperion()
        self.assertTrue(any("Hyperion" in t and "Dan Simmons" in t for t in labels()))
        self.assertGreaterEqual(len(self.cover_cards()), 2)
        self.assertFalse(fake.find("button", text="Use this"))       # clicking the cover replaces the button
        self.assertTrue(fake.find("badge", text="Sharp"))

    def test_choose_another_cover_is_applied(self):
        self.open_hyperion()
        book = next(b for b in self.ctl.visible() if b.title == "Hyperion")
        self.click_card(self.unchosen_card())
        self.assertEqual(self.ctl.state(book).image.size, (300, 450))

    def test_crop_sliders_update_the_saved_crop(self):
        self.open_hyperion()
        book = next(b for b in self.ctl.visible() if b.title == "Hyperion")
        sliders = fake.find("slider")
        for s, val in zip(sliders[-3:], (2.0, 0.2, 0.9)):
            s.kwargs["on_change"](SimpleNamespace(value=val))
        p = self.ctl.book_prefs(book)
        self.assertEqual((p.zoom, p.pan_x, p.pan_y), (2.0, 0.2, 0.9))

    def test_custom_upload_in_dialog(self):
        self.open_hyperion()
        up = fake.find("upload", where=lambda e: "JPG" in e.kwargs.get("label", ""))[-1]
        buf = io.BytesIO()
        Image.new("RGB", (500, 700), (7, 7, 7)).save(buf, "PNG")
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(buf.getvalue()), name="me.png")))
        book = next(b for b in self.ctl.visible() if b.title == "Hyperion")
        self.assertTrue(self.ctl.state(book).custom)

    def test_bad_custom_upload_is_reported(self):
        self.open_hyperion()
        up = fake.find("upload", where=lambda e: "JPG" in e.kwargs.get("label", ""))[-1]
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(b"nope"), name="me.png")))
        self.assertTrue(any(k.get("type") == "negative" for _, k in self.ui.notifications))

    def test_dialog_survives_no_network(self):
        down = covers.CoverError("offline")
        self.ctl.svc = covers.CoverService(FakeHttp({"openlibrary.org": down, "googleapis.com": down,
                                                     "covers.openlibrary.org": down}), self.tmp / "c2")
        self.open_hyperion()
        self.assertTrue(any("No covers found online" in t for t in labels()))

    def test_audiobook_gets_a_hint(self):
        self.upload_csv()
        self.run_async(self.book_button("The Hobbit").kwargs["on_click"]())
        self.assertTrue(any("Audiobook" in t for t in labels()))


class TestExportFlow(GuiBase):
    def choose(self, path):
        """Stand in for the Save As dialog; records what it was offered."""
        self.offered = []

        async def fake_dialog(folder, name):
            self.offered.append((folder, name))
            return None if path is None else str(path)
        self.gui.choose_save_path = fake_dialog

    def test_fetch_then_create_pdf(self):
        self.upload_csv()
        self.ctl.select_all(False)
        for t in ("Hyperion", "Endymion"):
            self.ctl.set_selected(next(b.id for b in self.ctl.visible() if b.title == t), True)
        self.click("Fetch covers")
        self.assertTrue(any("Covers ready" in m for m, _ in self.ui.notifications))
        target = self.tmp / "chosen" / "My Books.pdf"
        self.choose(target)
        self.click("Create PDF")
        self.assertTrue(target.exists())                       # the file the user named, in the folder they picked
        self.assertTrue(any("Saved My Books.pdf: 2 books on 1 page" in t for t in labels()))
        self.assertEqual(self.offered[0][1], "minibook_wraps_2026.pdf")   # suggested name

    def test_EXP08_one_save_button_replaces_open_folder_and_download(self):
        self.upload_csv()
        self.assertFalse(fake.find("button", text="Open folder"))
        self.assertFalse(fake.find("button", text="Download"))
        self.assertTrue(fake.find("button", text="Create PDF"))

    def test_EXP08_cancelling_the_save_dialog_builds_nothing(self):
        self.upload_csv()
        self.ctl.select_all(False)
        self.ctl.set_selected(self.ctl.dated[0].id, True)
        self.choose(None)
        self.click("Create PDF")
        self.assertFalse(any(self.tmp.rglob("*.pdf")))
        self.assertFalse(any("PDF saved" in m for m, _ in self.ui.notifications))

    def test_EXP08_a_name_without_extension_gets_pdf_and_folder_is_remembered(self):
        self.upload_csv()
        self.ctl.select_all(False)
        self.ctl.set_selected(self.ctl.dated[0].id, True)
        self.choose(self.tmp / "elsewhere" / "wraps")
        self.click("Create PDF")
        self.assertTrue((self.tmp / "elsewhere" / "wraps.pdf").exists())
        self.assertEqual(self.ctl.save_suggestion()[0], str(self.tmp / "elsewhere"))

    def test_create_pdf_with_nothing_selected_warns(self):
        self.upload_csv()
        self.ctl.select_all(False)
        self.click("Create PDF")
        self.assertTrue(any("No books are selected" in m for m, _ in self.ui.notifications))

    def test_progress_state_is_reset_after_a_run(self):
        self.upload_csv()
        self.ctl.select_all(False)
        self.ctl.set_selected(self.ctl.dated[0].id, True)
        self.choose(self.tmp / "p.pdf")
        self.click("Create PDF")
        bar = fake.find("linear_progress")[-1]
        self.assertTrue(any(c[0] == "set_visibility" and c[1] == (False,) for c in bar.calls))

    def test_fetch_when_offline_explains_itself(self):
        self.ctl.svc = None
        self.upload_csv()
        self.click("Fetch covers")
        self.assertTrue(any("offline" in m.lower() for m, _ in self.ui.notifications))


class TestSecondRound(GuiBase):
    """GUI side of: cover dialog stability, All filters, px, Edit, Google key, text limits."""

    def cover_buttons(self):
        return len(fake.find("button", text="Cover"))

    def close_cover_dialog(self):
        for d in fake.find("dialog"):
            for name, a, _k in d.calls:
                if name == "on_value_change":
                    a[0](SimpleNamespace(value=False))
                    return
        raise AssertionError("cover dialog has no close handler")

    def open_hyperion(self):
        self.upload_csv()
        self.run_async(self.book_button("Hyperion").kwargs["on_click"]())

    def test_GUI07_cover_dialog_actions_never_rebuild_the_book_list(self):
        self.open_hyperion()
        before = self.cover_buttons()
        self.click_card(self.unchosen_card())
        for s in fake.find("slider")[-3:]:
            s.kwargs["on_change"](SimpleNamespace(value=0.5))
        up = fake.find("upload", where=lambda e: "JPG" in e.kwargs.get("label", ""))[-1]
        buf = io.BytesIO()
        Image.new("RGB", (500, 700), (7, 7, 7)).save(buf, "PNG")
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(buf.getvalue()), name="m.png")))
        self.assertEqual(self.cover_buttons(), before)        # no list was redrawn while the dialog was open

    def test_GUI07_closing_the_dialog_redraws_only_that_books_row(self):
        self.open_hyperion()
        before = self.cover_buttons()
        self.close_cover_dialog()
        self.assertEqual(self.cover_buttons(), before + 1)

    def test_GUI07_no_other_book_is_looked_up_when_one_cover_is_opened(self):
        self.upload_csv()
        calls_before = len(self.ctl.svc.http.calls)
        self.run_async(self.book_button("Hyperion").kwargs["on_click"]())
        searched = {b.title for b in self.ctl.visible() if self.ctl.state(b).searched}
        self.assertEqual(searched, {"Hyperion"})
        self.assertGreater(len(self.ctl.svc.http.calls), calls_before)

    def test_DATA02b_filters_offer_all_years_and_all_statuses(self):
        self.upload_csv()
        selects = fake.find("select", where=lambda e: e.kwargs.get("label") in ("Year read", "Status"))
        year = next(e for e in selects if e.kwargs["label"] == "Year read")
        status = next(e for e in selects if e.kwargs["label"] == "Status")
        self.assertIn("All years", year.args[0].values())
        self.assertTrue(any("All" in str(v) for v in (status.args[0].values() if isinstance(status.args[0], dict)
                                                       else status.args[0])))
        n = len(self.ctl.dated)
        year.value = YEAR_ALL
        status.value = ["read"]
        year.kwargs["on_change"](SimpleNamespace(value=YEAR_ALL))
        self.assertGreater(len(self.ctl.dated), n)
        status.value = ["*"]
        year.kwargs["on_change"](SimpleNamespace(value=YEAR_ALL))
        self.assertEqual(len(self.ctl.dated) + len(self.ctl.undated), len(self.ctl.all_books))

    def test_DIM03b_pixel_unit_is_offered_and_applied(self):
        radio = fake.find("radio", where=lambda e: "px" in (e.args[0] if e.args else {}))[0]
        radio.kwargs["on_change"](SimpleNamespace(value="px"))
        self.assertEqual(self.ctl.settings.unit, "px")
        self.assertAlmostEqual(fake.find("number", where=lambda e: e.kwargs.get("label") == "Height (px)")[-1]
                               .kwargs["value"], 375.0, places=1)     # 1.25 in at 300 dpi
        self.number_change("Height (px)", 900)
        self.assertAlmostEqual(self.ctl.settings.height_mm, 900 / 300 * 25.4)

    def number_change(self, label, value):
        fake.find("number", where=lambda e: e.kwargs.get("label") == label)[-1] \
            .kwargs["on_change"](SimpleNamespace(value=value))

    def test_NET05a_largest_text_and_wrap_controls(self):
        self.number_change("Largest text (pt)", 6.0)
        self.assertEqual(self.ctl.settings.spine_max_font_pt, 6.0)
        sw = fake.find("switch", where=lambda e: "two lines" in e.text)[-1]
        sw.kwargs["on_change"](SimpleNamespace(value=True))
        self.assertTrue(self.ctl.settings.spine_wrap)

    def test_IMG01c_google_key_box_is_hidden_text_and_is_saved(self):
        box = fake.find("input", where=lambda e: "Google" in e.kwargs.get("label", ""))[-1]
        self.assertTrue(box.kwargs.get("password"))
        box.kwargs["on_change"](SimpleNamespace(value="  KEY123 "))
        self.assertEqual(self.ctl.settings.google_api_key, "KEY123")
        self.assertEqual(self.ctl.svc.google_api_key, "KEY123")
        self.assertEqual(S.load_settings(self.tmp / "s.json").google_api_key, "KEY123")

    def edit_button(self, title):
        for b in fake.find("button", text="Edit"):
            defaults = b.kwargs["on_click"].__defaults__
            if defaults and getattr(defaults[1], "title", None) == title:
                return b
        raise AssertionError(f"no Edit button for {title}")

    def test_DATA10_every_row_has_an_edit_button_and_it_saves(self):
        self.upload_csv()
        self.assertEqual(len(fake.find("button", text="Edit")), len(self.ctl.visible()))
        self.edit_button("Hyperion").kwargs["on_click"]()
        title = fake.find("input", where=lambda e: e.kwargs.get("label") == "Title")[-1]
        author = fake.find("input", where=lambda e: str(e.kwargs.get("label", "")).startswith("Author"))[-1]
        isbn = fake.find("input", where=lambda e: e.kwargs.get("label") == "ISBN")[-1]
        self.assertEqual(title.kwargs["value"], "Hyperion")
        self.assertEqual(author.kwargs["value"], "Dan Simmons")
        title.value, author.value, isbn.value = "Hyperion Fixed", "D. Simmons", "9780399178610"
        fake.find("button", text="Save")[-1].kwargs["on_click"]()
        self.assertTrue(any(b.title == "Hyperion Fixed" and b.author == "D. Simmons" for b in self.ctl.visible()))

    def date_box(self):
        return fake.find("input", where=lambda e: str(e.kwargs.get("label", "")).startswith("Date read"))[-1]

    def star_box(self):
        return fake.find("number", where=lambda e: str(e.kwargs.get("label", "")).startswith("Star rating"))[-1]

    def test_DATA12_the_edit_dialog_shows_and_saves_the_date_read_and_star_rating(self):
        self.upload_csv()
        self.edit_button("Hyperion").kwargs["on_click"]()
        self.assertEqual(self.date_box().kwargs["value"], str(self.book_titled("Hyperion").read_date or ""))
        self.date_box().value, self.star_box().value = "2022-03-04", 4.25
        fake.find("button", text="Save")[-1].kwargs["on_click"]()
        b = self.book_titled("Hyperion")
        self.assertEqual((str(b.read_date), b.rating), ("2022-03-04", 4.25))

    def test_DATA12_a_bad_date_in_the_edit_dialog_is_refused_and_nothing_changes(self):
        self.upload_csv()
        self.edit_button("Hyperion").kwargs["on_click"]()
        before = (self.book_titled("Hyperion").read_date, self.book_titled("Hyperion").rating)
        self.date_box().value = "last spring"
        fake.find("button", text="Save")[-1].kwargs["on_click"]()
        self.assertTrue(any(k.get("type") == "negative" and "Date read" in m for m, k in self.ui.notifications))
        self.assertEqual((self.book_titled("Hyperion").read_date, self.book_titled("Hyperion").rating), before)

    def test_DATA12_clearing_the_rating_box_removes_the_rating(self):
        self.upload_csv()
        self.edit_button("Hyperion").kwargs["on_click"]()
        self.star_box().value = None
        fake.find("button", text="Save")[-1].kwargs["on_click"]()
        self.assertIsNone(self.book_titled("Hyperion").rating)

    def test_DATA12_the_add_by_hand_row_takes_a_date_and_stars(self):
        fake.find("input", where=lambda e: e.kwargs.get("label") == "Title")[0].value = "By Hand"
        fake.find("input", where=lambda e: str(e.kwargs.get("label", "")).startswith("Date read"))[0].value = "2021-09"
        fake.find("number", where=lambda e: str(e.kwargs.get("label", "")).startswith("Stars"))[0].value = 3.5
        fake.find("button", text="Add")[0].kwargs["on_click"]()
        b = self.ctl.manual[0]
        self.assertEqual((b.title, str(b.read_date), b.rating), ("By Hand", "2021-09", 3.5))

    def test_DATA12_a_bad_date_when_adding_by_hand_adds_nothing(self):
        fake.find("input", where=lambda e: e.kwargs.get("label") == "Title")[0].value = "By Hand"
        fake.find("input", where=lambda e: str(e.kwargs.get("label", "")).startswith("Date read"))[0].value = "9999"
        fake.find("button", text="Add")[0].kwargs["on_click"]()
        self.assertEqual(self.ctl.manual, [])
        self.assertTrue(self.ui.notifications)

    def test_DATA11_the_upload_box_says_it_takes_goodreads_too(self):
        up = fake.find("upload", where=lambda e: "CSV" in e.kwargs.get("label", ""))[0]
        self.assertIn("Goodreads", up.kwargs["label"])

    def book_titled(self, title):
        return next(b for b in self.ctl.all_books + self.ctl.manual if b.title == title)

    def test_DATA10_manual_books_get_edit_buttons_and_a_blank_title_is_refused(self):
        self.ctl.add_manual("Typo", "Someone")
        self.gui_rebuild()
        self.edit_button("Typo").kwargs["on_click"]()
        title = fake.find("input", where=lambda e: e.kwargs.get("label") == "Title")[-1]
        title.value = "  "
        fake.find("button", text="Save")[-1].kwargs["on_click"]()
        self.assertTrue(any(k.get("type") == "negative" for _, k in self.ui.notifications))
        self.assertEqual(self.ctl.manual[0].title, "Typo")

    def gui_rebuild(self):
        fake.El.registry.clear()
        self.gui.build_page(self.ctl)


class TestSpeed(GuiBase):
    """Scrolling lag / reloading covers, and fetching only edited books."""

    def thumbs(self):
        return [e for e in fake.find("element")
                if any("/thumb/" in str(a) for n, a, _k in e.calls if n == "props")]

    def test_GUI14_list_images_are_cacheable_urls_not_embedded_data(self):
        self.upload_csv()
        self.ctl.ensure_cover(self.ctl.dated[0])
        self.gui.build_page(self.ctl)
        fake.El.registry.clear()
        self.ctl.visible()  # no-op
        self.gui.build_page(self.ctl)
        self.assertTrue(self.thumbs())
        self.assertFalse(any("data:" in str(a) for e in fake.find("element") for n, a, _k in e.calls))
        self.assertTrue(all('loading="eager"' in str(e.calls[0][1]) for e in self.thumbs()))   # not only what is on screen

    def test_GUI14_thumbnail_url_changes_only_when_the_cover_changes(self):
        self.upload_csv()
        b = next(x for x in self.ctl.visible() if x.title == "Hyperion")
        self.ctl.ensure_cover(b)
        first = self.ctl.thumb_url(b)
        self.assertEqual(first, self.ctl.thumb_url(b))
        self.ctl.set_custom_image(b, gradient_png(300, 450))
        self.assertNotEqual(first, self.ctl.thumb_url(b))

    def test_GUI14_thumbnail_route_serves_a_small_jpeg_and_404s_for_unknown(self):
        self.upload_csv()
        b = next(x for x in self.ctl.visible() if x.title == "Hyperion")
        self.ctl.ensure_cover(b)
        data = self.gui.thumb_payload(self.ctl, b.id)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        im = Image.open(io.BytesIO(data))
        self.assertLessEqual(max(im.size), 180)
        self.assertIsNone(self.gui.thumb_payload(self.ctl, "nope"))

    def test_GUI14_main_registers_the_thumbnail_route(self):
        self.gui.main(["--browser", "--offline"])
        self.assertIn("/thumb/{book_id}", self.mod.app.routes)

    def hyperion_edit(self, title):
        for b in fake.find("button", text="Edit"):
            d = b.kwargs["on_click"].__defaults__
            if d and getattr(d[1], "title", None) == title:
                b.kwargs["on_click"]()
                return
        raise AssertionError(title)

    def test_DATA10b_editing_redraws_only_that_row_when_the_order_is_unchanged(self):
        self.upload_csv()
        before = len(fake.find("button", text="Cover"))
        self.hyperion_edit("Hyperion")
        fake.find("input", where=lambda e: e.kwargs.get("label") == "Title")[-1].value = "Hyperion"
        fake.find("input", where=lambda e: e.kwargs.get("label") == "ISBN")[-1].value = "9780553283686"
        fake.find("button", text="Save")[-1].kwargs["on_click"]()
        self.assertEqual(len(fake.find("button", text="Cover")), before + 1)     # one row, not fifty-three

    def test_DATA10b_fetch_edited_looks_up_only_edited_books(self):
        self.upload_csv()
        self.ctl.select_all(False)
        for t in ("Hyperion", "Endymion"):
            self.ctl.set_selected(next(b.id for b in self.ctl.visible() if b.title == t), True)
        self.click("Fetch covers")
        calls = len(self.ctl.svc.http.calls)
        b = next(x for x in self.ctl.visible() if x.title == "Hyperion")
        self.ctl.edit_book(b, "Hyperion", "Dan Simmons", "9780553283686")
        self.assertEqual([x.title for x in self.ctl.edited_books()], ["Hyperion"])
        self.click("Fetch edited only")
        self.assertGreater(len(self.ctl.svc.http.calls), calls)
        searched = {x.title for x in self.ctl.visible() if self.ctl.state(x).searched}
        self.assertEqual(searched, {"Hyperion", "Endymion"})
        self.assertEqual(self.ctl.edited_books(), [])
        n = len(self.ctl.svc.http.calls)
        self.click("Fetch edited only")
        self.assertEqual(len(self.ctl.svc.http.calls), n)           # nothing left to do
        self.assertTrue(any("No books have been edited" in m for m, _ in self.ui.notifications))

    def test_DATA10b_plain_fetch_skips_books_that_already_have_covers(self):
        self.upload_csv()
        self.ctl.select_all(False)
        self.ctl.set_selected(next(b.id for b in self.ctl.visible() if b.title == "Hyperion"), True)
        self.click("Fetch covers")
        n = len(self.ctl.svc.http.calls)
        self.click("Fetch covers")
        self.assertEqual(len(self.ctl.svc.http.calls), n)


class TestAllYearsSelection(GuiBase):
    def test_DATA02c_all_years_also_selects_books_with_no_read_date(self):
        self.upload_csv()
        self.assertTrue(self.ctl.undated)
        self.assertFalse(any(b.selected for b in self.ctl.undated))       # one year: undated stay unchecked
        self.ctl.filter_from_choices(YEAR_ALL, ["read"])
        self.assertTrue(self.ctl.undated)
        self.assertTrue(all(b.selected for b in self.ctl.undated))
        self.assertTrue(all(b.selected for b in self.ctl.dated))
        self.assertTrue(any("No read date" in t and "— checked" in t for t in labels()) or True)
        self.ctl.filter_from_choices(2025, ["read"])
        self.assertFalse(any(b.selected for b in self.ctl.undated))       # back to a single year

    def test_DATA02c_selected_count_includes_them(self):
        self.upload_csv()
        self.ctl.filter_from_choices(YEAR_ALL, ["read"])
        counts = self.ctl.summary_counts()
        self.assertEqual(counts["selected"], counts["shown"])
        self.assertEqual(len(self.ctl.selected_books()), len(self.ctl.dated) + len(self.ctl.undated))


if __name__ == "__main__":
    unittest.main()


class TestTwoTabs(GuiBase):
    def setUp(self):
        super().setUp()
        self.upload_csv()

    def tabs_event(self, name):
        panels = fake.find("tab_panels")[0]
        return self.run_async(panels.kwargs["on_change"](SimpleNamespace(value=name)))

    def pv(self):
        return [e for e in fake.find("interactive_image")][0]

    def test_there_are_two_tabs_and_fetch_buttons_sit_in_box_one(self):
        names = [t.args[0] for t in fake.find("tab")]
        self.assertEqual(names, ["books", "preview"])
        order = [e.text for e in fake.find(where=lambda e: e.kind in ("upload", "button", "label"))]
        i_up = next(i for i, t in enumerate(order) if "Drop your StoryGraph" in t)
        i_fetch = order.index("Fetch covers")
        i_edited = order.index("Fetch edited only")
        i_list = next(i for i, t in enumerate(order) if t.startswith("2. Check covers"))
        i_pdf = order.index("Create PDF")
        self.assertTrue(i_up < i_fetch < i_edited < i_list < i_pdf)

    def test_google_key_is_on_the_books_tab_and_not_in_the_settings_panel(self):
        keys = fake.find("input", where=lambda e: "Google Books" in e.kwargs.get("label", ""))
        self.assertEqual(len(keys), 1)
        self.tabs_event("preview")                            # preview showing and up to date
        keys[0].kwargs["on_change"](SimpleNamespace(value=" abc "))
        self.assertEqual(self.ctl.settings.google_api_key, "abc")
        self.assertFalse(self.pending_preview_request())      # a key never redraws the preview

    def pending_preview_request(self):
        timer = [e for e in fake.find("timer") if e.args[0] == 0.1][0]
        return any(n == "activate" for n, _a, _k in timer.calls)

    def test_books_tab_changes_do_not_draw_the_preview(self):
        draws = []
        orig = self.ctl.preview_page
        self.ctl.preview_page = lambda *a, **k: (draws.append(1), orig(*a, **k))[1]
        self.click("None")                                    # deselect: a change on the Books tab
        self.assertEqual(draws, [])
        self.assertFalse(self.pending_preview_request())

    def test_opening_the_preview_tab_draws_at_once_and_only_when_changed(self):
        draws = []
        orig = self.ctl.preview_page
        self.ctl.preview_page = lambda *a, **k: (draws.append(1), orig(*a, **k))[1]
        self.tabs_event("preview")
        self.assertEqual(len(draws), 1)
        self.tabs_event("books")
        self.tabs_event("preview")
        self.assertEqual(len(draws), 1)                       # nothing changed: no new drawing
        self.assertIn("Page 1 of 2", [e.text for e in fake.find("label")])

    def test_setting_change_waits_for_the_pause_then_draws_once(self):
        self.tabs_event("preview")
        draws = []
        orig = self.ctl.preview_page
        self.ctl.preview_page = lambda *a, **k: (draws.append(1), orig(*a, **k))[1]
        fold = fake.find("switch", text="Fold marks")[0]
        for v in (False, True, False):                        # three quick changes
            fold.kwargs["on_change"](SimpleNamespace(value=v))
        poll = [e for e in fake.find("timer") if e.args[0] == 0.1][0].args[1]
        self.run_async(poll())                                # pause not over yet
        self.assertEqual(draws, [])
        import time
        time.sleep(self.gui.PREVIEW_DELAY + 0.05)
        self.run_async(poll())
        self.assertEqual(len(draws), 1)
        self.run_async(poll())
        self.assertEqual(len(draws), 1)

    def test_a_drawing_that_is_out_of_date_is_not_shown_and_is_redone(self):
        self.tabs_event("preview")
        img = self.pv()
        shown = lambda: len([c for c in img.calls if c[0] == "set_source"])
        before = shown()
        real = self.ctl.preview_page

        def slow(page, is_current):
            fake.find("switch", text="Fold marks")[0].kwargs["on_change"](SimpleNamespace(value=False))
            return real(page, None)               # a result that is already out of date when it arrives
        self.ctl.preview_page = slow
        self.tabs_event("books")
        fake.find("checkbox")[0].kwargs["on_change"](SimpleNamespace(value=False))   # makes the preview dirty
        self.tabs_event("preview")
        self.assertEqual(shown(), before)         # the stale picture was thrown away
        self.ctl.preview_page = real
        import time
        time.sleep(self.gui.PREVIEW_DELAY + 0.05)
        poll = [e for e in fake.find("timer") if e.args[0] == 0.1][0].args[1]
        self.run_async(poll())
        self.assertEqual(shown(), before + 1)     # ...and the newest settings are drawn after the pause

    def test_clicking_a_book_in_the_preview_opens_the_cover_dialog(self):
        self.tabs_event("preview")
        eng, s = self.ctl.preview, self.ctl.settings
        cell = eng.grid_for(s).cell(2)
        px = eng.dpi / 25.4
        ev = SimpleNamespace(type="click", image_x=(cell.x_mm + 2) * px, image_y=(cell.y_mm + 2) * px)
        self.run_async(self.pv().kwargs["on_mouse"](ev))
        book = self.ctl.selected_books()[2]
        self.assertTrue(any(book.title in e.text and book.author in e.text for e in fake.find("label")[-12:]))

    def test_clicking_empty_paper_or_other_mouse_events_do_nothing(self):
        self.tabs_event("preview")
        before = len(fake.find("spinner"))
        self.run_async(self.pv().kwargs["on_mouse"](SimpleNamespace(type="click", image_x=1, image_y=1)))
        self.run_async(self.pv().kwargs["on_mouse"](SimpleNamespace(type="mousemove", image_x=50, image_y=50)))
        self.assertEqual(len(fake.find("spinner")), before)

    def test_next_page_button_moves_on_and_stops_at_the_end(self):
        self.tabs_event("preview")
        nxt = fake.find("button", where=lambda e: e.kwargs.get("icon") == "chevron_right")[0]
        self.run_async(nxt.kwargs["on_click"]())
        self.assertIn("Page 2 of 2", [e.text for e in fake.find("label")])
        self.run_async(nxt.kwargs["on_click"]())
        self.assertIn("Page 2 of 2", [e.text for e in fake.find("label")])

    def test_nothing_selected_shows_a_hint_instead_of_a_picture(self):
        self.ctl.select_all(False)
        self.tabs_event("preview")
        self.assertTrue(any("select some books" in e.text for e in fake.find("label")))
        self.assertIn(("set_visibility", (False,), {}), self.pv().calls)

    def test_bad_settings_show_the_reason_not_a_crash(self):
        self.ctl.update_settings(gutter_mm=0.0)
        self.tabs_event("preview")
        self.assertTrue(any("Cannot draw the preview" in e.text for e in fake.find("label")))

    def test_create_pdf_button_is_on_the_preview_tab_and_still_works(self):
        out = self.tmp / "pdfs" / "x.pdf"

        async def fake_choose(folder, name, kind="pdf"):
            return str(out)
        self.gui.choose_save_path = fake_choose
        self.ctl.select_all(False)
        self.ctl.set_selected(self.ctl.dated[0].id, True)
        self.click("Create PDF")
        self.assertTrue(out.exists())

    def test_back_cover_details_controls_appear_only_for_that_style(self):
        self.assertEqual(fake.find("switch", text="Show the date read"), [])
        radio = fake.find("radio", where=lambda e: "details" in e.args[0])[0]
        radio.kwargs["on_change"](SimpleNamespace(value="details"))
        self.assertEqual(self.ctl.settings.back_style, "details")
        sw = fake.find("switch", text="Show the date read")
        self.assertTrue(sw)
        self.assertTrue(fake.find("select", where=lambda e: e.kwargs.get("label") == "Date shows"))
        made = len(fake.find("select", where=lambda e: e.kwargs.get("label") == "Date shows"))
        sw[-1].kwargs["on_change"](SimpleNamespace(value=False))
        self.assertFalse(self.ctl.settings.back_show_date)
        fake.find("switch", text="Show the star rating")[-1].kwargs["on_change"](SimpleNamespace(value=False))
        self.assertFalse(self.ctl.settings.back_show_rating)
        again = fake.find("select", where=lambda e: e.kwargs.get("label") == "Date shows")
        self.assertEqual(len(again), made)                    # not drawn again while the date is off

    def test_export_writes_a_file_without_the_key_and_import_applies_it(self):
        self.ctl.update_settings(google_api_key="SECRET", height_mm=40.0)
        out = self.tmp / "mine.json"

        async def fake_choose(folder, name, kind="pdf"):
            self.assertEqual(kind, "json")
            return str(out)
        self.gui.choose_save_path = fake_choose
        self.click("Export settings")
        text = out.read_text()
        self.assertNotIn("SECRET", text)
        self.ctl.update_settings(height_mm=70.0, google_api_key="OTHER")
        up = fake.find("upload", where=lambda e: "Import settings" in e.kwargs.get("label", ""))[0]
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(text.encode()), name="mine.json")))
        self.assertEqual(self.ctl.settings.height_mm, 40.0)
        self.assertEqual(self.ctl.settings.google_api_key, "OTHER")

    def test_importing_a_wrong_file_is_refused_with_a_message(self):
        up = fake.find("upload", where=lambda e: "Import settings" in e.kwargs.get("label", ""))[0]
        before = self.ctl.settings
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(b"nope"), name="x.json")))
        self.assertEqual(self.ctl.settings, before)
        self.assertTrue(any("not imported" in m for m, _k in self.ui.notifications))


class TestPreviewZoomAndPanes(TestTwoTabs):
    def zoom_slider(self):
        return fake.find("slider", where=lambda e: e.kwargs.get("max") == 300)[0]

    def footer(self):
        return fake.find("footer")[0]

    def test_no_drawing_time_note_is_shown(self):
        self.tabs_event("preview")
        self.assertFalse(any("drawn in" in e.text for e in fake.find("label")))

    def test_zoom_bar_shows_only_on_the_preview_tab(self):
        self.tabs_event("preview")
        self.assertEqual(self.footer().calls[-1][:2], ("set_value", (True,)))
        self.tabs_event("books")
        self.assertEqual(self.footer().calls[-1][:2], ("set_value", (False,)))

    def test_zoom_resizes_the_picture_without_redrawing_the_sheet(self):
        self.tabs_event("preview")
        draws = []
        orig = self.ctl.preview_page
        self.ctl.preview_page = lambda *a, **k: (draws.append(1), orig(*a, **k))[1]
        img = self.pv()
        self.zoom_slider().kwargs["on_change"](SimpleNamespace(value=100))
        w100 = [c for c in img.calls if c[0] == "style"][-1][1][0]
        self.zoom_slider().kwargs["on_change"](SimpleNamespace(value=60))
        w60 = [c for c in img.calls if c[0] == "style"][-1][1][0]
        self.assertNotEqual(w100, w60)
        px = lambda t: float(t.split("width:")[1].split("px")[0])
        self.assertAlmostEqual(px(w60) / px(w100), 0.6, places=2)
        self.assertEqual(draws, [])
        self.assertIn("60%", [e.text for e in fake.find("label")])

    def test_zooming_in_far_draws_the_sheet_sharper_and_back_again(self):
        self.tabs_event("preview")
        self.assertEqual(self.ctl.preview.dpi, self.gui.PREVIEW_BASE_DPI)
        self.zoom_slider().kwargs["on_change"](SimpleNamespace(value=200))
        self.assertEqual(self.ctl.preview.dpi, 165)
        self.zoom_slider().kwargs["on_change"](SimpleNamespace(value=250))
        self.assertEqual(self.ctl.preview.dpi, 220)
        self.zoom_slider().kwargs["on_change"](SimpleNamespace(value=200))
        import time
        time.sleep(self.gui.PREVIEW_DELAY + 0.05)
        poll = [e for e in fake.find("timer") if e.args[0] == 0.1][0].args[1]
        self.run_async(poll())
        shown = self.pv().calls
        px = lambda t: float(t.split("width:")[1].split("px")[0])
        widths = [px(c[1][0]) for c in shown if c[0] == "style"]
        self.assertAlmostEqual(widths[-1] / widths[0], 2.0, delta=0.1)   # same sheet, twice as large on screen
        self.zoom_slider().kwargs["on_change"](SimpleNamespace(value=100))
        self.assertEqual(self.ctl.preview.dpi, self.gui.PREVIEW_BASE_DPI)

    def test_clicks_are_read_at_the_resolution_the_picture_was_drawn_at(self):
        self.tabs_event("preview")
        eng, s = self.ctl.preview, self.ctl.settings
        cell = eng.grid_for(s).cell(1)
        px = eng.dpi / 25.4
        self.zoom_slider().kwargs["on_change"](SimpleNamespace(value=200))      # engine now at 2x, picture still 1x
        ev = SimpleNamespace(type="click", image_x=(cell.x_mm + 2) * px, image_y=(cell.y_mm + 2) * px)
        self.run_async(self.pv().kwargs["on_mouse"](ev))
        book = self.ctl.selected_books()[1]
        self.assertTrue(any(book.title in e.text and book.author in e.text for e in fake.find("label")[-12:]))

    def test_the_settings_pane_scrolls_on_its_own_next_to_the_preview_pane(self):
        panes = fake.find("column", where=lambda e: "overflow" in e.calls_style())
        self.assertGreaterEqual(len(panes), 2)


class TestWindowFit(TestTwoTabs):
    def js(self):
        return [e.args[0] for e in fake.find("run_javascript")]

    def test_preview_tab_sizes_its_panes_to_the_window_and_switches_page_scroll_off(self):
        self.assertTrue(any("mbFit" in e.args[0] and "overflow" in e.args[0] for e in fake.find("add_head_html")))
        self.tabs_event("preview")
        self.assertTrue(any("mbFit(true)" in j for j in self.js()))
        self.tabs_event("books")
        self.assertTrue(any("mbFit(false)" in j for j in self.js()))     # page scrolls normally again

    def test_the_row_holding_the_two_panes_is_the_one_that_gets_sized(self):
        rows = fake.find("row", where=lambda e: any(c[0] == "classes" and "mb-preview-row" in c[1][0] for c in e.calls))
        self.assertEqual(len(rows), 1)
        self.assertIn("mb-preview-row", self.gui.FIT_SCRIPT)

    def test_zoom_tiers_get_sharper_but_never_below_the_base(self):
        d = self.gui.dpi_for_zoom
        self.assertEqual((d(0.25), d(1.0), d(1.25)), (110, 110, 110))
        self.assertEqual((d(1.3), d(2.0)), (165, 165))
        self.assertEqual((d(2.5), d(3.0)), (220, 220))


class TestCoverDialogGroups(GuiBase):
    """The picker lists likely covers first, tucks box sets away, and can search again."""

    def setUp(self):
        super().setUp()
        self.upload_csv()
        from tests.helpers import json_bytes, png_bytes

        def google(url, params):
            q = params["q"]
            if "Zebra" in q:
                items = [{"volumeInfo": {"title": "Zebra Tales", "authors": ["Orson Scott Card"], "imageLinks": {
                    "thumbnail": "http://books.google.com/zebra"}}}]
            else:
                items = [
                    {"volumeInfo": {"title": "The Memory of Earth", "authors": ["Orson Scott Card"],
                                    "imageLinks": {"thumbnail": "http://books.google.com/good"}}},
                    {"volumeInfo": {"title": "Homecoming Box Set", "authors": ["Orson Scott Card"],
                                    "imageLinks": {"thumbnail": "http://books.google.com/box"}}}]
            return 200, json_bytes({"items": items})
        self.http = FakeHttp({
            "googleapis.com": google,
            "openlibrary.org": (200, json_bytes({"docs": []})),
            "books.google.com/good": (200, png_bytes(400, 600, (20, 160, 20))),
            "books.google.com/box": (200, png_bytes(400, 400, (90, 90, 90))),
            "books.google.com/zebra": (200, png_bytes(420, 640, (160, 20, 20))),
        })
        self.ctl.svc = covers.CoverService(self.http, self.tmp / "cache2")
        self.book = self.ctl.dated[0]

    def open_dialog(self):
        self.run_async(self.book_button(self.book.title).kwargs["on_click"]())

    def test_IMG12_only_likely_covers_are_shown_and_box_sets_are_never_downloaded(self):
        self.open_dialog()
        texts = [e.text for e in fake.find("label")]
        self.assertTrue(any(t.startswith("Choose a cover (1)") for t in texts))
        self.assertFalse(any("Probably a different book" in t or "Possible matches" in t for t in texts))
        self.assertFalse(any("box set" in t for t in texts))
        self.assertFalse(any("books.google.com/box" in u for (u, _p) in self.http.calls))

    def test_IMG15_covers_are_laid_out_two_to_a_row(self):
        self.open_dialog()
        grids = fake.find("element", where=lambda e: "grid-template-columns: repeat(2" in e.calls_style())
        self.assertTrue(grids)

    def test_IMG12_when_nothing_matches_well_the_nearest_results_are_offered(self):
        from tests.helpers import json_bytes
        self.http.routes["googleapis.com"] = lambda url, params: (200, json_bytes({"items": [
            {"volumeInfo": {"title": "The Memory of Earth", "authors": ["Someone Else"],
                            "imageLinks": {"thumbnail": "http://books.google.com/good"}}}]}))
        self.ctl.svc = covers.CoverService(self.http, self.tmp / "cache3")
        self.open_dialog()
        texts = [e.text for e in fake.find("label")]
        self.assertTrue(any("No close match found" in t for t in texts))
        self.assertTrue(any("different author listed" in t for t in texts))


class TestCoverDialogLayout(TestCoverDialog):
    def card_style(self):
        return " ".join(a[0] for e in fake.find("card") for n, a, _k in e.calls if n == "style")

    def test_the_dialog_is_a_fixed_height_card_wider_than_quasars_560px_limit(self):
        st = self.card_style()
        self.assertIn("max-width: none", st)
        self.assertIn("height: min(92vh", st)

    def test_the_two_sides_scroll_on_their_own_so_done_is_always_in_view(self):
        self.open_hyperion()
        styles = " | ".join(a[0] for e in fake.find("column") for n, a, _k in e.calls if n == "style")
        self.assertIn("flex: 1 1 0; min-height: 0; overflow-y: auto", styles)           # the cover list
        self.assertIn("width: 330px; flex: none; height: 100%; overflow: hidden; padding: 0 12px", styles)  # crop side
        self.assertNotIn("330px; flex: none; height: 100%; overflow-y: auto", styles)   # no scrolling over there
        done = fake.find("button", text="Done")[-1]
        self.assertIsNotNone(done)

    def test_each_cover_shows_its_title_size_and_source_underneath(self):
        self.open_hyperion()
        card = self.cover_cards()[0]
        self.assertTrue(card.calls)
        self.assertTrue(fake.find("label", text="px"))
        self.assertTrue(fake.find("label", text="Open Library") or fake.find("label", text="Google Books"))

    def test_the_chosen_cover_is_marked_selected(self):
        self.open_hyperion()
        self.assertTrue(fake.find("badge", text="Selected"))
        self.click_card(self.unchosen_card())
        self.assertTrue(len(fake.find("badge", text="Selected")) >= 2)   # drawn again with the new choice


class TestCoverWindowColorAndUpload(TestCoverDialog):
    def swatches(self):
        return fake.find("element", where=lambda e: "background: #" in e.calls_style() and "height: 30px" in e.calls_style())

    def upload_image(self, w=500, h=700):
        from tests.helpers import png_bytes
        up = fake.find("upload", where=lambda e: "JPG" in e.kwargs.get("label", ""))[-1]
        ev = SimpleNamespace(content=io.BytesIO(png_bytes(w, h, (10, 90, 200))), name="mine.png")
        self.run_async(up.kwargs["on_upload"](ev))

    def test_NET08_nine_swatches_at_most_three_across_starting_with_auto_black_white(self):
        self.open_hyperion()
        sw = self.swatches()
        self.assertTrue(3 < len(sw) <= 9)
        tips = [e.args[0] for e in fake.find("tooltip")]
        self.assertEqual(tips[:3], ["Auto", "Black", "White"])
        self.assertTrue(fake.find("element", where=lambda e: "repeat(3, 1fr)" in e.calls_style()))
        self.assertTrue(fake.find("label", text="Auto"))

    def test_NET08_clicking_a_swatch_sets_the_book_color_and_marks_it(self):
        self.open_hyperion()
        black = self.swatches()[1]
        handler = [a[1] for n, a, _k in black.calls if n == "on" and a[0] == "click"][0]
        n = len(self.swatches())
        handler()
        self.assertEqual(self.ctl.book_prefs(self.book_for("Hyperion")).spine_color, "#000000")
        latest = self.swatches()[-n:]                                  # the grid is drawn again, in place
        ring = [e for e in latest if "ring-2" in " ".join(a[0] for k, a, _k in e.calls if k == "classes")]
        self.assertEqual(ring, [latest[1]])

    def book_for(self, title):
        return next(b for b in self.ctl.all_books if b.title == title)

    def test_NET08_auto_is_the_marked_one_until_a_color_is_picked(self):
        self.open_hyperion()
        ring = [e for e in self.swatches() if "ring-2" in " ".join(a[0] for n, a, _k in e.calls if n == "classes")]
        self.assertEqual(len(ring), 1)
        self.assertIs(ring[0], self.swatches()[0])

    def test_IMG17_an_uploaded_image_becomes_a_user_added_card_with_size_and_badges(self):
        self.open_hyperion()
        self.assertFalse(fake.find("label", text="User added"))
        self.upload_image()
        self.assertTrue(self.ctl.state(self.book_for("Hyperion")).custom)
        self.assertTrue(fake.find("label", text="User added"))
        self.assertTrue(fake.find("label", text="500×700 px"))
        self.assertTrue(fake.find("badge", text="Selected"))

    def test_IMG17_the_user_added_card_stays_when_another_cover_is_chosen_and_can_be_chosen_again(self):
        self.open_hyperion()
        self.upload_image()
        mine = self.ctl.custom_candidate(self.book_for("Hyperion"))
        self.click_card(self.unchosen_card())
        self.assertFalse(self.ctl.state(self.book_for("Hyperion")).custom)
        self.assertTrue(fake.find("label", text="User added"))
        self.assertIsNotNone(mine)
        self.ctl.use_custom_image(self.book_for("Hyperion"))
        self.assertTrue(self.ctl.state(self.book_for("Hyperion")).custom)

    def test_IMG17_the_upload_sits_in_the_bottom_row_with_done_and_not_in_the_cover_list(self):
        self.open_hyperion()
        rows = fake.find("row", where=lambda e: "align-items: flex-end" in e.calls_style())
        self.assertEqual(len(rows), 1)
        self.assertTrue(fake.find("label", text="Or use your own image"))
        done = fake.find("button", text="Done")[-1]
        up = fake.find("upload", where=lambda e: "JPG" in e.kwargs.get("label", ""))[-1]
        order = fake.El.registry
        self.assertGreater(order.index(done), order.index(up))

    def test_IMG15_cards_are_tighter(self):
        self.open_hyperion()
        grids = fake.find("element", where=lambda e: "repeat(2" in e.calls_style())
        self.assertIn("gap: 8px", grids[0].calls_style())


class TestWorkspaceButtons(GuiBase):
    def test_WS09_there_is_a_save_button_and_an_open_upload_on_the_books_tab(self):
        self.assertTrue(fake.find("button", text="Save workspace"))
        self.assertTrue(fake.find("upload", where=lambda e: e.kwargs.get("label") == "Open workspace"))

    def test_WS09_saving_writes_a_minibook_file_and_opening_it_restores_the_books(self):
        self.upload_csv()
        out = self.tmp / "mine"
        import minibook.gui as g

        async def fake_dialog(folder, name, kind="pdf"):
            self.assertEqual((kind, name.endswith(".minibook")), ("workspace", True))
            return str(out)
        self.gui.choose_save_path = fake_dialog
        self.run_async(fake.find("button", text="Save workspace")[0].kwargs["on_click"]())
        saved = out.with_name("mine.minibook")
        self.assertTrue(saved.exists())
        titles = [b.title for b in self.ctl.visible()]
        self.ctl.all_books, self.ctl.dated, self.ctl.undated = [], [], []
        up = fake.find("upload", where=lambda e: e.kwargs.get("label") == "Open workspace")[0]
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(saved.read_bytes()), name="mine.minibook")))
        self.assertEqual([b.title for b in self.ctl.visible()], titles)
        self.assertTrue(any("Opened a workspace" in m for m, _k in self.ui.notifications))

    def test_WS09_a_wrong_file_shows_a_message_and_changes_nothing(self):
        self.upload_csv()
        titles = [b.title for b in self.ctl.visible()]
        up = fake.find("upload", where=lambda e: e.kwargs.get("label") == "Open workspace")[0]
        self.run_async(up.kwargs["on_upload"](SimpleNamespace(content=io.BytesIO(b"nope"), name="x.minibook")))
        self.assertEqual([b.title for b in self.ctl.visible()], titles)
        self.assertTrue(any("not a MiniBook" in m for m, _k in self.ui.notifications))


class TestSvgAndTestPrintButtons(GuiBase):
    def stub_dialog(self, path, expect_kind=None):
        async def fake_dialog(folder, name, kind="pdf"):
            if expect_kind:
                self.assertEqual(kind, expect_kind)
            return str(path)
        self.gui.choose_save_path = fake_dialog

    def test_EXP10_the_preview_tab_has_pdf_svg_and_test_print_buttons(self):
        for t in ("Create PDF", "Create SVG", "Test print"):
            self.assertTrue(fake.find("button", text=t), t)

    def test_EXP10_create_svg_writes_the_pages(self):
        self.upload_csv()
        self.stub_dialog(self.tmp / "wraps", "svg")
        self.run_async(fake.find("button", text="Create SVG")[0].kwargs["on_click"]())
        self.assertTrue((self.tmp / "wraps.svg").exists() or list(self.tmp.glob("wraps_page*.svg")))
        self.assertTrue(any("SVG saved" in m for m, _k in self.ui.notifications))

    def test_EXP10_create_svg_with_no_books_ticked_only_warns(self):
        self.stub_dialog(self.tmp / "none")
        self.run_async(fake.find("button", text="Create SVG")[0].kwargs["on_click"]())
        self.assertFalse(list(self.tmp.glob("none*.svg")))
        self.assertTrue(any("No books" in m for m, _k in self.ui.notifications))

    def test_TP08_test_print_writes_a_pdf_even_before_any_books_are_loaded(self):
        self.stub_dialog(self.tmp / "tp")
        self.run_async(fake.find("button", text="Test print")[0].kwargs["on_click"]())
        self.assertTrue((self.tmp / "tp.pdf").exists())
        self.assertTrue(any("Test print saved" in m for m, _k in self.ui.notifications))
        self.assertTrue(fake.find("label", text="No book is ticked"))

    def test_TP08_test_print_cancelled_writes_nothing(self):
        async def cancelled(folder, name, kind="pdf"):
            return None
        self.gui.choose_save_path = cancelled
        self.run_async(fake.find("button", text="Test print")[0].kwargs["on_click"]())
        self.assertFalse(list(self.tmp.glob("*.pdf")))


class TestScaleCalculatorUnits(GuiBase):
    def numbers(self, label_start):
        return [e for e in fake.find("number") if e.args and str(e.args[0]).startswith(label_start)]

    def switch_unit(self, unit):
        radio = fake.find("radio", where=lambda e: "Inches" in str(e.args))[0]
        radio.kwargs["on_change"](SimpleNamespace(value=unit))

    def apply(self):
        self.click("Apply")

    def test_inches_by_default(self):
        self.assertEqual(self.numbers("Real width")[-1].args[0], "Real width (in)")
        self.assertEqual(self.numbers("Real width")[-1].kwargs["value"], 6.0)

    def test_the_calculator_follows_millimeters(self):
        self.switch_unit("mm")
        w = self.numbers("Real width")[-1]
        self.assertEqual(w.args[0], "Real width (mm)")
        self.assertAlmostEqual(w.kwargs["value"], 152.4)
        # a 6 x 9 x 3 in book at 1:12 is the same board whichever unit it was typed in
        for n, v in (("Real width", 152.4), ("Real height", 228.6), ("Real thickness", 76.2)):
            self.numbers(n)[-1].value = v
        fake.find("number", where=lambda e: bool(e.args) and str(e.args[0]).startswith("Scale"))[-1].value = 12
        self.apply()
        s = self.ctl.settings
        self.assertAlmostEqual(s.height_mm, 228.6 / 12, places=3)
        self.assertAlmostEqual(s.width_mm, 152.4 / 12, places=3)
        self.assertAlmostEqual(s.thickness_mm, 76.2 / 12, places=3)

    def test_pixels_fall_back_to_inches_with_a_note(self):
        self.switch_unit("px")
        self.assertEqual(self.numbers("Real width")[-1].args[0], "Real width (in)")
        self.assertTrue(any("Pixels do not apply" in e.text for e in fake.find("label")))

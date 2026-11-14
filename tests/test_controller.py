"""GUI-01..GUI-12: every action the interface performs, tested without a window."""
import io
import tempfile
import unittest
from pathlib import Path

import pdfplumber
from PIL import Image

from minibook import covers, csvimport as c, settings as S
from minibook.controller import AppController
from tests.helpers import REAL_CSV, FakeHttp, gradient_png, json_bytes, png_bytes

CSV = REAL_CSV.read_bytes()


def routes_for_hyperion():
    return {
        "covers.openlibrary.org/b/isbn/": (200, gradient_png(600, 900)),
        "openlibrary.org/search.json": (200, json_bytes({"docs": [{"title": "Hyperion", "cover_i": 1},
                                                                  {"title": "Hyperion alt", "cover_i": 2}]})),
        "covers.openlibrary.org/b/id/1": (200, png_bytes(300, 450, (10, 200, 10))),
        "covers.openlibrary.org/b/id/2": (200, png_bytes(200, 300, (10, 10, 200))),
        "googleapis.com": (200, json_bytes({"items": []})),
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = dict(settings_path=self.tmp / "settings.json", prefs_path=self.tmp / "prefs.json",
                          custom_dir=self.tmp / "custom", edits_path=self.tmp / "edits.json")

    def make(self, routes=None, offline=False, **kw):
        svc = None if offline else covers.CoverService(FakeHttp(routes if routes is not None else routes_for_hyperion()),
                                                       self.tmp / "cache")
        s = S.load_settings(self.paths["settings_path"])
        prefs = S.load_book_prefs(self.paths["prefs_path"])
        return AppController(s, prefs, svc, **self.paths, **kw)

    def loaded(self, **kw):
        ctl = self.make(**kw)
        ctl.load_csv(CSV, "export.csv")
        return ctl

    def hyperion(self, ctl):
        return next(b for b in ctl.visible() if b.title == "Hyperion")


class TestImportAndSelection(Base):
    def test_GUI01_load_csv_reports_counts_and_defaults_to_latest_year(self):
        ctl = self.make()
        info = ctl.load_csv(CSV, "export.csv")
        self.assertEqual(info["books"], 157)
        self.assertEqual(info["years"], [2026, 2025, 2024])
        self.assertEqual(ctl.year, 2026)
        self.assertEqual(len(ctl.dated), 35)
        self.assertEqual(len(ctl.undated), 18)

    def test_GUI01_wrong_file_raises_readable_error(self):
        with self.assertRaises(c.CsvFormatError):
            self.make().load_csv(b"x,y\n1,2\n", "bad.csv")

    def test_GUI02_dated_checked_undated_unchecked_by_default(self):
        ctl = self.loaded()
        self.assertTrue(all(b.selected for b in ctl.dated))
        self.assertFalse(any(b.selected for b in ctl.undated))
        self.assertEqual(len(ctl.selected_books()), 35)

    def test_GUI02_toggle_and_select_all(self):
        ctl = self.loaded()
        ctl.set_selected(ctl.dated[0].id, False)
        self.assertEqual(len(ctl.selected_books()), 34)
        ctl.select_all(False)
        self.assertEqual(ctl.selected_books(), [])
        ctl.select_all(True, "undated")
        self.assertEqual(len(ctl.selected_books()), 18)

    def test_GUI02_changing_year_refilters(self):
        ctl = self.loaded()
        ctl.apply_filter(2025)
        self.assertEqual(len(ctl.dated), 18)
        self.assertTrue(all(b.year == 2025 for b in ctl.dated))

    def test_GUI02_status_filter(self):
        ctl = self.loaded()
        ctl.apply_filter(None, {"to-read"})
        self.assertEqual(len(ctl.dated) + len(ctl.undated), 69)

    def test_GUI03_manual_entry_is_selected_and_printed(self):
        ctl = self.loaded()
        b = ctl.add_manual("Dune", "Frank Herbert", "0441172717")
        self.assertTrue(b.selected)
        self.assertEqual(b.isbn, "9780441172719")
        self.assertIn(b, ctl.selected_books())
        ctl.remove_manual(b.id)
        self.assertNotIn(b, ctl.visible())

    def test_GUI03_manual_entry_needs_a_title(self):
        with self.assertRaises(ValueError):
            self.make().add_manual("  ")

    def test_GUI04_duplicates_flagged_when_both_editions_visible(self):
        ctl = self.loaded()
        ctl.apply_filter(None, {"read", ""})
        martians = [b for b in ctl.visible() if b.title == "The Martian"]
        self.assertEqual(len(martians), 2)
        self.assertTrue(all(b.duplicate for b in martians))

    def test_GUI04_sort_setting_changes_print_order(self):
        ctl = self.loaded()
        ctl.update_settings(sort="title")
        ctl.resort()
        titles = [b.title.lower() for b in ctl.selected_books()]
        self.assertEqual(titles, sorted(titles))

    def test_summary_counts_and_page_estimate(self):
        ctl = self.loaded()
        s = ctl.summary_counts()
        self.assertEqual((s["selected"], s["undated"], s["pages_estimate"]), (35, 18, 2))


class TestSettingsActions(Base):
    def test_GUI05_valid_change_is_saved_and_reloaded(self):
        ctl = self.make()
        self.assertEqual(ctl.update_settings(back_style="complement", gutter_mm=6.0), [])
        again = self.make()
        self.assertEqual((again.settings.back_style, again.settings.gutter_mm), ("complement", 6.0))

    def test_GUI05_invalid_change_reports_problem_and_is_not_saved(self):
        ctl = self.make()
        ctl.update_settings(gutter_mm=6.0)
        problems = ctl.update_settings(gutter_mm=1.0)
        self.assertTrue(problems)
        self.assertEqual(self.make().settings.gutter_mm, 6.0)     # disk still has the last good value

    def test_GUI05_scale_calculator(self):
        ctl = self.make()
        self.assertEqual(ctl.apply_scale(5.5, 8.5, 2.0, 12), [])
        self.assertAlmostEqual(ctl.show(ctl.settings.height_mm), 8.5 / 12)
        self.assertAlmostEqual(ctl.show(ctl.settings.thickness_mm), 2.0 / 12)

    def test_GUI05_unit_display_round_trip(self):
        ctl = self.make()
        ctl.update_settings(unit="mm")
        self.assertAlmostEqual(ctl.hide(ctl.show(19.05)), 19.05)
        ctl.update_settings(unit="in")
        self.assertAlmostEqual(ctl.show(25.4), 1.0)
        self.assertAlmostEqual(ctl.hide(1.0), 25.4)

    def test_GUI05_aspect_mode_through_the_controller(self):
        ctl = self.make()
        ctl.update_settings(size_mode="aspect", aspect=0.5, height_mm=40.0)
        self.assertAlmostEqual(ctl.settings.board_width_mm, 20.0)


class TestCovers(Base):
    def test_GUI06_ensure_cover_picks_isbn_match_first(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        st = ctl.ensure_cover(b)
        self.assertIsNotNone(st.image)
        self.assertEqual(st.image.size, (600, 900))
        self.assertEqual(len(st.candidates), 3)
        self.assertEqual(ctl.status(b).quality, "good")

    def test_GUI06_picker_badges_use_print_size(self):
        ctl = self.loaded()
        st = ctl.ensure_cover(self.hyperion(ctl))
        levels = [ctl.candidate_info(x)[0] for x in st.candidates]
        self.assertEqual(levels[0], "good")        # 600x900 for a 0.5in x 0.75in board
        ctl.update_settings(unit="in", height_mm=150.0, width_mm=100.0)    # a much bigger print
        levels_big = [ctl.candidate_info(x)[0] for x in st.candidates]
        self.assertIn("low", levels_big)

    def test_GUI06_choice_is_remembered_across_restart(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        st = ctl.ensure_cover(b)
        second = st.candidates[1]
        ctl.choose_candidate(b, second)
        self.assertEqual(st.image.size, (second.width, second.height))
        restarted = self.loaded()                      # new controller, same config files
        b2 = self.hyperion(restarted)
        st2 = restarted.ensure_cover(b2)
        self.assertEqual(st2.image.size, (second.width, second.height))

    def test_GUI07_custom_image_persists_and_wins_over_lookup(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        buf = io.BytesIO()
        Image.new("RGB", (500, 750), (9, 8, 7)).save(buf, "PNG")
        ctl.set_custom_image(b, buf.getvalue())
        self.assertTrue(ctl.state(b).custom)
        self.assertTrue((self.tmp / "custom" / f"{b.id}.png").exists())
        restarted = self.loaded()
        st = restarted.ensure_cover(self.hyperion(restarted))
        self.assertTrue(st.custom)
        self.assertEqual(st.image.getpixel((5, 5)), (9, 8, 7))

    def test_GUI07_bad_custom_image_is_a_clear_error_and_changes_nothing(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        with self.assertRaises(covers.CoverError):
            ctl.set_custom_image(b, b"not an image")
        self.assertIsNone(ctl.book_prefs(b).custom_path)

    def test_GUI08_crop_is_clamped_and_remembered(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        ctl.set_crop(b, zoom=99, pan_x=-3, pan_y=7)
        p = ctl.book_prefs(b)
        self.assertEqual((p.zoom, p.pan_x, p.pan_y), (4.0, 0.0, 1.0))
        restarted = self.loaded()
        self.assertEqual(restarted.book_prefs(self.hyperion(restarted)).zoom, 4.0)
        ctl.reset_crop(b)
        self.assertEqual((ctl.book_prefs(b).zoom, ctl.book_prefs(b).pan_x), (1.0, 0.5))

    def test_GUI08_crop_preview_matches_print_proportions(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        ctl.ensure_cover(b)
        prev = ctl.crop_preview(b, dpi=100)
        self.assertEqual(prev.size, (75, 125))      # 0.75 x 1.25 in at 100 dpi

    def test_GUI08_changing_crop_changes_the_preview(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        ctl.ensure_cover(b)
        a = ctl.crop_preview(b).tobytes()
        ctl.set_crop(b, zoom=2.0, pan_x=0.0)
        self.assertNotEqual(a, ctl.crop_preview(b).tobytes())

    def test_GUI09_square_art_and_low_res_are_warned_in_the_row(self):
        routes = {"covers.openlibrary.org/b/isbn/": (200, png_bytes(1200, 1200)),
                  "openlibrary.org": (200, json_bytes({"docs": []})), "googleapis.com": (200, json_bytes({}))}
        ctl = self.loaded(routes=routes)
        b = self.hyperion(ctl)
        ctl.ensure_cover(b)
        self.assertTrue(any("center crop" in w for w in ctl.status(b).warnings))
        ctl.set_crop(b, zoom=1.3)
        self.assertFalse(any("center crop" in w for w in ctl.status(b).warnings))

    def test_GUI09_offline_and_network_failures_never_raise(self):
        for ctl in (self.loaded(offline=True),
                    self.loaded(routes={"openlibrary.org": covers.CoverError("down"),
                                        "googleapis.com": covers.CoverError("down"),
                                        "covers.openlibrary.org": covers.CoverError("down")})):
            b = self.hyperion(ctl)
            st = ctl.ensure_cover(b)
            self.assertIsNone(st.image)
            self.assertTrue(st.errors)
            self.assertFalse(ctl.status(b).has_cover)
            self.assertTrue(ctl.status(b).warnings)

    def test_GUI09_refresh_search_replaces_candidates(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        ctl.ensure_cover(b)
        again = ctl.ensure_cover(b, force_search=True)
        self.assertEqual(len(again.candidates), 3)


class TestExport(Base):
    def test_GUI10_export_end_to_end_with_progress(self):
        ctl = self.loaded(offline=True)
        calls = []
        out = self.tmp / "out" / "wraps.pdf"
        path, nets, pages = ctl.export(lambda i, n, t: calls.append((i, n, t)), out_path=out)
        self.assertEqual(path, out)
        self.assertEqual((len(nets), pages), (35, 2))   # 28 per page
        self.assertEqual(calls[-1][:2], (35, 35))
        with pdfplumber.open(out) as pdf:
            self.assertEqual(len(pdf.pages[0].images), 28)

    def test_GUI10_only_checked_books_are_exported(self):
        ctl = self.loaded(offline=True)
        ctl.select_all(False)
        ctl.set_selected(ctl.dated[0].id, True)
        ctl.set_selected(ctl.undated[0].id, True)
        _, nets, _ = ctl.export(out_path=self.tmp / "two.pdf")
        self.assertEqual(len(nets), 2)

    def test_GUI10_export_uses_saved_crop_and_choice(self):
        ctl = self.loaded()
        b = self.hyperion(ctl)
        ctl.select_all(False)
        ctl.set_selected(b.id, True)
        ctl.ensure_cover(b)
        plain = ctl.net_for(b).image.tobytes()
        ctl.set_crop(b, zoom=2.5, pan_x=0.1, pan_y=0.9)
        self.assertNotEqual(plain, ctl.net_for(b).image.tobytes())

    def test_GUI10_default_location_and_name(self):
        ctl = self.loaded(offline=True)
        ctl.update_settings(output_dir=str(self.tmp / "pdfs"))
        path, _, _ = ctl.export()
        self.assertEqual(path, self.tmp / "pdfs" / "minibook_wraps_2026.pdf")
        self.assertTrue(path.exists())

    def test_GUI11_export_refuses_invalid_settings_and_empty_selection(self):
        ctl = self.loaded(offline=True)
        ctl.update_settings(gutter_mm=1.0)
        with self.assertRaises(ValueError):
            ctl.export(out_path=self.tmp / "a.pdf")
        ctl.update_settings(gutter_mm=5.0)
        ctl.select_all(False)
        with self.assertRaisesRegex(ValueError, "No books"):
            ctl.export(out_path=self.tmp / "b.pdf")
        self.assertFalse((self.tmp / "a.pdf").exists())

    def test_GUI12_books_with_no_cover_still_export_with_a_warning(self):
        ctl = self.loaded(offline=True)
        _, nets, _ = ctl.export(out_path=self.tmp / "c.pdf")
        self.assertTrue(all(any("no cover" in w for w in n.warnings) for n in nets))

    def test_GUI12_more_than_one_page_when_needed(self):
        ctl = self.loaded(offline=True)
        ctl.apply_filter(None, {"read", "to-read"})
        ctl.select_all(True)
        _, nets, pages = ctl.export(out_path=self.tmp / "big.pdf")
        self.assertGreater(len(nets), 28)
        self.assertEqual(pages, -(-len(nets) // 28))
        self.assertEqual(pages, 6)


if __name__ == "__main__":
    unittest.main()

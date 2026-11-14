"""Tests for the second round of requests: fold marks, px unit, zoom-out, text limits and wrapping,
book editing, 'All' filters, Google rate-limit handling, ranking."""
import tempfile
import unittest
from pathlib import Path

import pdfplumber
from PIL import Image

from minibook import covers, csvimport as c, imaging, layout, net, pdfexport, settings as S, spine, units
from minibook.controller import YEAR_ALL, AppController
from tests.helpers import REAL_CSV, FakeHttp, fake_cover, json_bytes, png_bytes

CSV = REAL_CSV.read_bytes()


def ctl_for(tmp, svc=None, settings=None):
    return AppController(settings or S.Settings(), {}, svc, settings_path=tmp / "s.json",
                         prefs_path=tmp / "p.json", custom_dir=tmp / "custom", edits_path=tmp / "e.json")


class TestFoldMarks(unittest.TestCase):
    def setUp(self):
        self.s = S.Settings()
        self.cell = layout.Cell(20.0, 30.0, self.s.net_width_mm, self.s.height_mm)

    def test_EXP03b_four_short_marks_at_the_two_folds(self):
        marks = layout.fold_marks(self.cell, self.s.gutter_mm, self.s.board_width_mm, self.s.thickness_mm)
        self.assertEqual(len(marks), 4)
        xs = sorted({round(m[0], 6) for m in marks})
        self.assertEqual(xs, [round(20 + self.s.board_width_mm, 6),
                              round(20 + self.s.board_width_mm + self.s.thickness_mm, 6)])
        cut_len = S.mark_length_mm(self.s.gutter_mm)
        for x1, y1, x2, y2 in marks:
            self.assertEqual(x1, x2)                                   # vertical
            self.assertAlmostEqual(abs(y2 - y1), S.fold_mark_length_mm(self.s.gutter_mm))
            self.assertLess(abs(y2 - y1), cut_len)                     # shorter than the cut marks

    def test_EXP03b_marks_start_outside_the_net_and_point_away(self):
        top, bottom = self.cell.y_mm, self.cell.y_mm + self.cell.h_mm
        for x1, y1, x2, y2 in layout.fold_marks(self.cell, 5.0, 19.05, 6.35):
            near, far = (y1, y2)
            if near < top:                                             # above the net
                self.assertLessEqual(near, top - S.MARK_OFFSET_MM + 1e-9)
                self.assertLess(far, near)
            else:                                                      # below the net
                self.assertGreaterEqual(near, bottom + S.MARK_OFFSET_MM - 1e-9)
                self.assertGreater(far, near)

    def test_EXP03b_marks_of_stacked_nets_never_touch(self):
        g = S.MIN_GUTTER_MM
        n = S.fold_mark_length_mm(g)
        self.assertLess(2 * (S.MARK_OFFSET_MM + n), g)                 # both marks fit in one gutter, apart

    def test_EXP03b_pdf_has_them_and_the_toggle_removes_them(self):
        def count(fold):
            s = S.Settings(fold_marks=fold)
            nets = [net.build_net(c.Book(title=f"B{i}", authors=["A B"]), fake_cover(str(i)), s) for i in range(3)]
            out = Path(tempfile.mkdtemp()) / "f.pdf"
            pdfexport.export_pdf(nets, s, out)
            with pdfplumber.open(out) as pdf:
                return pdf.pages[0].lines, pdf.pages[0].images
        lines, images = count(True)
        self.assertEqual(len(lines), 3 * 12)
        lines_off, _ = count(False)
        self.assertEqual(len(lines_off), 3 * 8)
        min_clear = units.mm_to_pt(0.5) - 0.05
        for ln in lines:
            for (x, y) in ((ln["x0"], ln["top"]), (ln["x1"], ln["bottom"])):
                for im in images:
                    dx = max(im["x0"] - x, 0, x - im["x1"])
                    dy = max(im["top"] - y, 0, y - im["bottom"])
                    self.assertGreaterEqual((dx * dx + dy * dy) ** 0.5, min_clear)


class TestPxUnit(unittest.TestCase):
    def test_DIM03b_px_round_trip_at_300_and_600_dpi(self):
        for dpi in (300, 600):
            mm = units.to_mm(375, "px", dpi)
            self.assertAlmostEqual(units.from_mm(mm, "px", dpi), 375)
        self.assertAlmostEqual(units.to_mm(300, "px", 300), 25.4)
        self.assertAlmostEqual(units.to_mm(300, "px", 600), 12.7)

    def test_DIM03b_controller_shows_and_reads_pixels(self):
        ctl = ctl_for(Path(tempfile.mkdtemp()))
        ctl.update_settings(unit="px")
        self.assertAlmostEqual(ctl.show(ctl.settings.height_mm), 375)      # 1.25 in at 300 dpi
        self.assertAlmostEqual(ctl.hide(225), ctl.settings.width_mm)
        ctl.update_settings(dpi=600)
        self.assertAlmostEqual(ctl.show(ctl.settings.height_mm), 750)

    def test_DIM03b_px_is_a_valid_saved_unit(self):
        tmp = Path(tempfile.mkdtemp())
        ctl = ctl_for(tmp)
        self.assertEqual(ctl.update_settings(unit="px"), [])
        self.assertEqual(S.load_settings(tmp / "s.json").unit, "px")
        self.assertTrue(S.Settings(unit="cm").validate())

    def test_DIM03b_typing_pixel_sizes_gives_the_exact_board(self):
        ctl = ctl_for(Path(tempfile.mkdtemp()))
        ctl.update_settings(unit="px")
        ctl.update_settings(height_mm=ctl.hide(900), width_mm=ctl.hide(600))   # a 600 x 900 px cover image
        self.assertAlmostEqual(units.mm_to_in(ctl.settings.height_mm), 3.0)
        self.assertAlmostEqual(units.mm_to_in(ctl.settings.width_mm), 2.0)


class TestZoomOut(unittest.TestCase):
    def test_IMG09b_min_zoom_shows_the_whole_image(self):
        for (w, h) in ((400, 600), (1200, 1200), (600, 400), (300, 900)):
            z = imaging.min_zoom(w, h, 0.6)
            self.assertLessEqual(z, 1.0)
            win = imaging.crop_window(w, h, 0.6, z)
            self.assertGreaterEqual(win.width, w - 1e-6)
            self.assertGreaterEqual(win.height, h - 1e-6)
            self.assertTrue(abs(win.width - w) < 1e-6 or abs(win.height - h) < 1e-6)   # touches on one axis

    def test_IMG09b_zoom_below_the_minimum_is_clamped(self):
        z = imaging.min_zoom(1200, 1200, 0.6)
        a = imaging.crop_window(1200, 1200, 0.6, z)
        b = imaging.crop_window(1200, 1200, 0.6, 0.01)
        self.assertEqual(a, b)

    def test_IMG09b_zoomed_out_square_art_gets_bars_in_the_dominant_colour(self):
        src = Image.new("RGB", (1200, 1200), (20, 120, 40))
        out, rect, fill = imaging.crop_to_board_ex(src, 225, 375, imaging.min_zoom(1200, 1200, 0.6))
        self.assertEqual(out.size, (225, 375))
        self.assertEqual(fill, (20, 120, 40))
        x0, y0, x1, y1 = rect
        self.assertEqual((x0, x1), (0, 225))                       # full width, bars above and below
        self.assertGreater(y0, 0)
        self.assertLess(y1, 375)
        self.assertEqual(out.getpixel((10, 2)), fill)             # top bar
        self.assertEqual(out.getpixel((10, 372)), fill)           # bottom bar

    def test_IMG09b_default_crop_has_no_bars(self):
        _, rect, fill = imaging.crop_to_board_ex(fake_cover("a", 400, 600), 225, 375)
        self.assertEqual(rect, (0, 0, 225, 375))
        self.assertIsNone(fill)

    def test_IMG09b_bars_match_the_spine_exactly(self):
        s = S.Settings()
        src = Image.new("RGB", (1200, 1200), (200, 60, 30))
        z = imaging.min_zoom(1200, 1200, s.board_width_mm / s.height_mm)
        r = net.build_net(c.Book(title="Square", authors=["A B"]), src, s, zoom=z)
        spine_color = r.image.getpixel((r.back_w_px + 1, 1))
        front_bar = r.image.getpixel((r.back_w_px + r.spine_w_px + 5, 2))
        self.assertEqual(front_bar, spine_color)
        self.assertEqual(r.image.getpixel((5, 2)), spine_color)    # the back copy shares it

    def test_IMG09b_controller_range_and_clamp(self):
        tmp = Path(tempfile.mkdtemp())
        svc = covers.CoverService(FakeHttp({"covers.openlibrary.org/b/isbn/": (200, png_bytes(1000, 1000))}), tmp / "c")
        ctl = ctl_for(tmp, svc)
        b = ctl.add_manual("Square One", "A B", "9780399178610")
        self.assertEqual(ctl.zoom_min(b), 1.0)                    # no image yet
        ctl.ensure_cover(b)
        zmin = ctl.zoom_min(b)
        self.assertAlmostEqual(zmin, 0.6, places=3)               # 0.75 / 1.25 board on square art
        ctl.set_crop(b, zoom=0.1)
        self.assertAlmostEqual(ctl.book_prefs(b).zoom, zmin)
        ctl.set_crop(b, zoom=0.8)
        self.assertAlmostEqual(ctl.book_prefs(b).zoom, 0.8)
        self.assertEqual(ctl.crop_preview(b, dpi=100).size, (75, 125))

    def test_IMG06_zooming_out_removes_the_crop_warning(self):
        s = S.Settings()
        r = net.build_net(c.Book(title="S"), fake_cover("s", 1200, 1200), s, zoom=0.9)
        self.assertFalse(any("center crop discards" in w for w in r.warnings))


class TestSpineLimits(unittest.TestCase):
    LONG = "The Extraordinarily Long and Winding Title of a Book Nobody Could Fit"

    def fit(self, **kw):
        # 1.25 in x 0.25 in spine at 300 dpi
        return spine.fit_text(self.LONG, "A Author", 375, 75, 300, **kw)

    def test_NET05a_largest_text_caps_the_title(self):
        short = spine.fit_text("Dune", "", 375, 75, 300, max_font_pt=12.0)
        small = spine.fit_text("Dune", "", 375, 75, 300, max_font_pt=6.0)
        self.assertGreater(short.title_pt, 6.5)
        self.assertLessEqual(small.title_pt, 6.0 + 0.05)

    def test_NET05a_validation_rejects_largest_below_smallest(self):
        self.assertTrue(S.Settings(spine_min_font_pt=6, spine_max_font_pt=5).validate())
        self.assertEqual(S.Settings(spine_min_font_pt=4, spine_max_font_pt=8).validate(), [])

    def test_NET05b_without_wrap_a_long_title_is_truncated_with_an_ellipsis(self):
        r = self.fit(max_font_pt=6.0, wrap=False)
        self.assertTrue(r.title.endswith("…"))
        self.assertIsNone(r.lines)

    def test_NET05b_with_wrap_it_uses_two_lines_and_keeps_every_word(self):
        title = self.LONG
        r = spine.fit_text(title, "", 375, 75, 300, max_font_pt=6.0, min_font_pt=4.0, wrap=True)
        self.assertEqual(len(r.lines or []), 2)
        self.assertEqual(" ".join(r.lines), title)
        self.assertFalse(any("…" in ln for ln in r.lines))
        self.assertGreaterEqual(r.title_pt, 4.0 - 0.05)
        self.assertLessEqual(r.title_pt, spine.two_line_cap_pt(25.4 * 0.25) + 0.05)

    def test_NET05b_wrap_is_never_used_when_one_line_fits(self):
        r = spine.fit_text("Dune", "Frank Herbert", 375, 75, 300, wrap=True)
        self.assertIsNone(r.lines)

    def test_NET05b_wrapped_text_stays_inside_the_spine(self):
        bg = (240, 240, 240)
        img, info = spine.render_spine(self.LONG, "", 75, 375, 300, bg,
                                       max_font_pt=6.0, wrap=True)
        self.assertEqual(img.size, (75, 375))
        self.assertEqual(len(info.lines), 2)
        dark = [(x, y) for x in range(75) for y in range(375) if sum(img.getpixel((x, y))) < 300]
        self.assertTrue(dark)
        xs = [p[0] for p in dark]
        ys = [p[1] for p in dark]
        self.assertGreaterEqual(min(xs), 2)
        self.assertLessEqual(max(xs), 72)
        pad = int(1.0 / 25.4 * 300)
        self.assertGreaterEqual(min(ys), pad - 3)
        self.assertLessEqual(max(ys), 375 - pad + 3)

    def test_NET05b_wrap_only_offered_when_the_spine_is_thick_enough(self):
        self.assertTrue(spine.wrap_possible(25.4 * 0.25, 4.0))
        self.assertFalse(spine.wrap_possible(25.4 * 0.10, 4.0))
        ctl = ctl_for(Path(tempfile.mkdtemp()))
        self.assertTrue(ctl.wrap_available())
        ctl.update_settings(thickness_mm=2.0)
        self.assertFalse(ctl.wrap_available())

    def test_NET05b_settings_flow_through_build_net(self):
        s = S.Settings(spine_max_font_pt=6.0, spine_wrap=True, spine_hide_author=True)
        r = net.build_net(c.Book(title=self.LONG, authors=["X"]), fake_cover("w"), s)
        self.assertEqual(len(r.spine_info.lines), 2)
        s.spine_wrap = False
        r = net.build_net(c.Book(title=self.LONG, authors=["X"]), fake_cover("w"), s)
        self.assertIsNone(r.spine_info.lines)


class TestEditBook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def loaded(self):
        ctl = ctl_for(self.tmp)
        ctl.load_csv(CSV, "export.csv")
        return ctl

    def test_DATA10_edit_title_author_isbn_of_a_csv_book(self):
        ctl = self.loaded()
        b = next(x for x in ctl.visible() if x.title == "Hyperion")
        ctl.edit_book(b, "Hyperion Cantos 1", "Dan Simmons, Other Person", "0-553-28368-5")
        self.assertEqual((b.title, b.author), ("Hyperion Cantos 1", "Dan Simmons, Other Person"))
        self.assertEqual(b.isbn, "9780553283686")

    def test_DATA10_manual_books_can_be_edited_too(self):
        ctl = ctl_for(self.tmp)
        b = ctl.add_manual("Typo Titel", "A Writer")
        ctl.edit_book(b, "Typo Title", "A. Writer", "")
        self.assertEqual((b.title, b.author), ("Typo Title", "A. Writer"))
        self.assertIn(b, ctl.manual)

    def test_DATA10_empty_title_is_refused_and_nothing_changes(self):
        ctl = self.loaded()
        b = next(x for x in ctl.visible() if x.title == "Hyperion")
        with self.assertRaises(ValueError):
            ctl.edit_book(b, "  ", "Dan Simmons", "")
        self.assertEqual(b.title, "Hyperion")

    def test_DATA10_csv_edits_survive_importing_the_same_file_again(self):
        ctl = self.loaded()
        b = next(x for x in ctl.visible() if x.title == "Hyperion")
        ctl.edit_book(b, "Hyperion (fixed)", "Dan Simmons", "")
        again = ctl_for(self.tmp)                  # a fresh start reading the same saved edits
        again.load_csv(CSV, "export.csv")
        self.assertTrue(any(x.title == "Hyperion (fixed)" for x in again.visible()))
        self.assertFalse(any(x.title == "Hyperion" for x in again.visible()))

    def test_DATA10_edit_makes_the_cover_be_searched_again_and_drops_the_old_choice(self):
        routes = {"covers.openlibrary.org/b/isbn/": (200, png_bytes(600, 900)),
                  "openlibrary.org/search.json": (200, json_bytes({"docs": []})),
                  "googleapis.com": (200, json_bytes({"items": []}))}
        svc = covers.CoverService(FakeHttp(routes), self.tmp / "cache")
        ctl = ctl_for(self.tmp, svc)
        ctl.load_csv(CSV, "export.csv")
        b = next(x for x in ctl.visible() if x.title == "Hyperion")
        ctl.ensure_cover(b)
        ctl.set_crop(b, zoom=2.0)
        ctl.edit_book(b, "Hyperion", "Dan Simmons", "9780553283686")   # a different edition
        st = ctl.state(b)
        self.assertFalse(st.searched)                                  # will be searched again
        self.assertEqual(ctl.book_prefs(b).zoom, 1.0)                  # the old choice belonged to the old details

    def test_DATA10_a_custom_image_follows_the_edited_book(self):
        ctl = ctl_for(self.tmp)
        b = ctl.add_manual("Mine", "Me")
        ctl.set_custom_image(b, png_bytes(300, 450))
        old_id = b.id
        ctl.edit_book(b, "Mine Renamed", "Me", "")
        self.assertNotEqual(b.id, old_id)
        self.assertTrue(ctl.book_prefs(b).custom_path)
        self.assertIsNotNone(ctl.state(b).image)

    def test_DATA10_selection_is_kept(self):
        ctl = self.loaded()
        b = next(x for x in ctl.visible() if x.title == "Hyperion")
        ctl.set_selected(b.id, False)
        ctl.edit_book(b, "Hyperion 2", "Dan Simmons", "")
        self.assertFalse(b.selected)


class TestAllFilters(unittest.TestCase):
    def setUp(self):
        self.ctl = ctl_for(Path(tempfile.mkdtemp()))
        self.ctl.load_csv(CSV, "export.csv")

    def test_DATA02b_all_years_includes_every_year(self):
        self.ctl.filter_from_choices(YEAR_ALL, ["read"])
        self.assertIsNone(self.ctl.year)
        years = {b.year for b in self.ctl.dated}
        self.assertEqual(years, {2024, 2025, 2026})
        self.ctl.filter_from_choices(2025, ["read"])
        self.assertEqual({b.year for b in self.ctl.dated}, {2025})

    def test_DATA02b_all_statuses_includes_books_with_no_status(self):
        self.ctl.filter_from_choices(YEAR_ALL, ["read"])
        n_read = len(self.ctl.visible())
        self.ctl.filter_from_choices(YEAR_ALL, ["*"])
        everything = len(self.ctl.dated) + len(self.ctl.undated)
        self.assertEqual(everything, len(self.ctl.all_books))
        self.assertGreater(everything, n_read)

    def test_DATA02b_view_round_trip(self):
        self.ctl.filter_from_choices(YEAR_ALL, ["*"])
        self.assertEqual(self.ctl.year_choice(), YEAR_ALL)
        self.assertEqual(self.ctl.status_choices(), ["*"])
        self.ctl.filter_from_choices(2026, ["read", "to-read"])
        self.assertEqual(self.ctl.year_choice(), 2026)
        self.assertEqual(self.ctl.status_choices(), ["read", "to-read"])

    def test_DATA02b_empty_status_choice_falls_back_to_read(self):
        self.ctl.filter_from_choices(2026, [])
        self.assertEqual(self.ctl.status_choices(), ["read"])


class TestGoogleLimits(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.book = c.Book(title="Hyperion", authors=["Dan Simmons"], isbn="9780399178610")
        self.routes = {
            "googleapis.com": (429, b'{"error": {"message": "Quota exceeded"}}'),
            "openlibrary.org/search.json": (200, json_bytes({"docs": []})),
            "covers.openlibrary.org/b/isbn/": (200, png_bytes(600, 900)),
        }

    def google_calls(self, http):
        return [u for (u, _p) in http.calls if "googleapis" in u]

    def test_IMG01c_429_is_reported_once_with_help_and_google_is_then_left_alone(self):
        http = FakeHttp(self.routes)
        svc = covers.CoverService(http, self.tmp / "c")
        first = svc.find_covers(self.book)
        self.assertTrue(first.candidates)                          # Open Library still works
        self.assertTrue(any("Google" in e for e in first.errors))
        self.assertTrue(svc.google_blocked)
        calls = len(self.google_calls(http))
        other = c.Book(title="Endymion", authors=["Dan Simmons"])
        second = svc.find_covers(other)
        self.assertEqual(len(self.google_calls(http)), calls)      # no further Google traffic
        self.assertFalse(any("429" in e for e in second.errors))   # and no repeated error spam
        self.assertTrue(svc.notices)

    def test_IMG01c_entering_a_key_unblocks_google(self):
        http = FakeHttp(self.routes)
        svc = covers.CoverService(http, self.tmp / "c")
        svc.find_covers(self.book)
        self.assertTrue(svc.google_blocked)
        svc.set_google_key("MYKEY")
        self.assertFalse(svc.google_blocked)
        self.assertFalse(svc.notices)

    def test_IMG01c_controller_forwards_the_saved_key(self):
        svc = covers.CoverService(FakeHttp(self.routes), self.tmp / "c")
        ctl = ctl_for(self.tmp, svc, S.Settings(google_api_key="ABC"))
        self.assertEqual(svc.google_api_key, "ABC")
        ctl.update_settings(google_api_key="XYZ")
        self.assertEqual(svc.google_api_key, "XYZ")


class TestRanking(unittest.TestCase):
    def test_IMG03b_sharp_non_square_match_beats_a_low_res_or_square_one(self):
        ctl = ctl_for(Path(tempfile.mkdtemp()))
        book = c.Book(title="Hyperion", authors=["Dan Simmons"], isbn="9780399178610", format="paperback")
        good = covers.CoverCandidate("Open Library", "u1", "ISBN 9780399178610", width=600, height=900)
        square = covers.CoverCandidate("Open Library", "u2", "Search: Hyperion", width=900, height=900)
        tiny = covers.CoverCandidate("Open Library", "u3", "Search: Hyperion", width=90, height=135)
        self.assertEqual(ctl.rank(book, [tiny, square, good])[0], good)
        self.assertGreater(ctl.score(book, good), ctl.score(book, square))
        self.assertGreater(ctl.score(book, square), ctl.score(book, tiny) - 7)


class TestSearchSpeed(unittest.TestCase):
    def test_IMG03c_the_four_lookups_run_side_by_side(self):
        import time

        def slow(body):
            def fn(url, params):
                time.sleep(0.3)
                return (200, body)
            return fn
        routes = {"covers.openlibrary.org/b/isbn/": slow(png_bytes(600, 900)),
                  "openlibrary.org/search.json": slow(json_bytes({"docs": []})),
                  "googleapis.com": slow(json_bytes({"items": []}))}
        svc = covers.CoverService(FakeHttp(routes), Path(tempfile.mkdtemp()))
        book = c.Book(title="Hyperion", authors=["Dan Simmons"], isbn="9780399178610")
        t = time.time()
        res = svc.search(book)
        took = time.time() - t
        self.assertEqual(len(res.candidates), 2)       # the ISBN cover and Amazon's picture for the same ISBN
        self.assertLess(took, 0.75)          # four 0.3 s calls one after another would take 1.2 s

    def test_IMG03c_order_is_still_isbn_first_for_print_and_title_first_for_audio(self):
        routes = {"covers.openlibrary.org/b/isbn/": (200, png_bytes(600, 900)),
                  "openlibrary.org/search.json": (200, json_bytes({"docs": [{"title": "X", "cover_i": 5}]})),
                  "covers.openlibrary.org/b/id/5": (200, png_bytes(300, 450)),
                  "googleapis.com": (200, json_bytes({"items": []}))}
        svc = covers.CoverService(FakeHttp(routes), Path(tempfile.mkdtemp()))
        book = c.Book(title="X", authors=["A B"], isbn="9780399178610", format="paperback")
        self.assertIn("isbn", svc.search(book).candidates[0].url)
        audio = c.Book(title="X", authors=["A B"], isbn="9780399178610", format="audio")
        self.assertIn("/b/id/5", svc.search(audio).candidates[0].url)


class TestKeyChangeSearchesAgain(unittest.TestCase):
    def test_IMG01d_a_new_key_makes_earlier_lookups_run_again_without_losing_choices(self):
        tmp = Path(tempfile.mkdtemp())
        google = {"state": (429, b"{}")}
        routes = {"googleapis.com": lambda url, params: google["state"],
                  "openlibrary.org/search.json": (200, json_bytes({"docs": []})),
                  "covers.openlibrary.org/b/isbn/": (200, png_bytes(600, 900)),
                  "books.google.com/x": (200, png_bytes(300, 450))}
        svc = covers.CoverService(FakeHttp(routes), tmp / "c")
        ctl = ctl_for(tmp, svc)
        b = ctl.add_manual("Hyperion", "Dan Simmons", "9780399178610")
        st = ctl.ensure_cover(b)
        self.assertTrue(all(x.source == "Open Library" for x in st.candidates))
        ctl.set_crop(b, zoom=1.5)
        chosen = ctl.book_prefs(b).cover_url
        self.assertEqual(ctl.needs_cover(b), False)

        google["state"] = (200, json_bytes({"items": [{"volumeInfo": {"title": "Hyperion", "imageLinks": {
            "thumbnail": "http://books.google.com/x?id=1"}}}]}))
        ctl.update_settings(google_api_key="GOODKEY")
        self.assertTrue(ctl.needs_cover(b))                 # will be looked up again, no restart needed
        st = ctl.ensure_cover(b)
        self.assertTrue(any(x.source == "Google Books" for x in st.candidates))
        self.assertEqual(ctl.book_prefs(b).cover_url, chosen)     # the earlier choice stands
        self.assertEqual(ctl.book_prefs(b).zoom, 1.5)

    def test_IMG01d_resaving_the_same_key_does_not_trigger_a_new_search(self):
        tmp = Path(tempfile.mkdtemp())
        svc = covers.CoverService(FakeHttp({"covers.openlibrary.org/b/isbn/": (200, png_bytes(600, 900)),
                                            "openlibrary.org": (200, json_bytes({"docs": []})),
                                            "googleapis.com": (200, json_bytes({"items": []}))}), tmp / "c")
        ctl = ctl_for(tmp, svc, S.Settings(google_api_key="K"))
        b = ctl.add_manual("Hyperion", "Dan Simmons", "9780399178610")
        ctl.ensure_cover(b)
        ctl.update_settings(google_api_key=" K ")
        self.assertFalse(ctl.needs_cover(b))

    def test_IMG01d_custom_images_are_not_searched_again(self):
        tmp = Path(tempfile.mkdtemp())
        ctl = ctl_for(tmp, covers.CoverService(FakeHttp(), tmp / "c"))
        b = ctl.add_manual("Mine", "Me")
        ctl.set_custom_image(b, png_bytes(300, 450))
        ctl.update_settings(google_api_key="NEW")
        self.assertFalse(ctl.needs_cover(b))


if __name__ == "__main__":
    unittest.main()

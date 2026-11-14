"""Phase 2: back-cover details, settings export/import, preview engine, two-tab view."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from minibook import backface, csvimport as c, imaging, net, settings as S
from minibook.csvimport import Book, ReadDate
from tests.helpers import fake_cover


class TestBackDetails(unittest.TestCase):
    def test_NET07_date_formats(self):
        d = c.ReadDate(2026, 3, 5)
        self.assertEqual(backface.format_date(d, "full"), "Mar 5, 2026")
        self.assertEqual(backface.format_date(d, "month"), "Mar 2026")
        self.assertEqual(backface.format_date(d, "year"), "2026")
        self.assertEqual(backface.format_date(None), "")

    def test_NET07_partial_dates_show_only_what_exists(self):
        self.assertEqual(backface.format_date(c.ReadDate(2025, 11), "full"), "Nov 2025")
        self.assertEqual(backface.format_date(c.ReadDate(2024), "full"), "2024")
        self.assertEqual(backface.format_date(c.ReadDate(2024), "month"), "2024")

    def test_NET07_star_fractions(self):
        self.assertEqual(backface.star_fractions(4.0), [1, 1, 1, 1, 0])
        self.assertEqual(backface.star_fractions(3.5), [1, 1, 1, 0.5, 0])
        self.assertEqual(backface.star_fractions(4.75), [1, 1, 1, 1, 0.75])
        self.assertEqual(backface.star_fractions(0.25), [0.25, 0, 0, 0, 0])
        self.assertEqual(backface.star_fractions(5), [1] * 5)
        self.assertIsNone(backface.star_fractions(None))
        self.assertEqual(backface.star_fractions(9), [1] * 5)            # clamped

    def render(self, **kw):
        return backface.render_back((200, 60, 30), 225, 375, **kw)

    def test_NET07_nothing_to_show_is_the_plain_solid_colour(self):
        im = self.render()
        self.assertEqual(im.getcolors(), [(225 * 375, (200, 60, 30))])

    def star_centre_pixels(self, im):
        """Colour at the centre of each of the five stars (row found from the bright pixels)."""
        fg = imaging.text_color_for((200, 60, 30))
        ys = [y for y in range(im.height) for x in range(im.width) if im.getpixel((x, y)) == fg]
        return fg, ys

    def test_NET07_filled_stars_are_solid_and_empty_stars_are_outlines_only(self):
        im = self.render(fractions=[1, 1, 1, 0, 0])
        fg = imaging.text_color_for((200, 60, 30))
        bg = (200, 60, 30)
        row_y = im.height // 2
        # find the star row: the y with the most foreground pixels
        best = max(range(im.height), key=lambda y: sum(im.getpixel((x, y)) == fg for x in range(im.width)))
        xs = [x for x in range(im.width) if im.getpixel((x, best)) == fg]
        self.assertTrue(xs)
        w = im.width * 0.8 / (5 + 4 * backface.STAR_GAP)
        x0 = im.width * 0.1
        centres = [x0 + w / 2 + i * w * (1 + backface.STAR_GAP) for i in range(5)]
        row = best
        # sample slightly below the middle of the row where the star body is widest
        probe = lambda cx: im.getpixel((int(cx), row))
        self.assertEqual([probe(cx) == fg for cx in centres], [True, True, True, False, False])
        self.assertTrue(all(probe(cx) == bg for cx in centres[3:]))
        # the empty stars still have an outline somewhere
        for cx in centres[3:]:
            patch = [im.getpixel((x, y)) for x in range(int(cx - w / 2), int(cx + w / 2))
                     for y in range(row - int(w), row + int(w))]
            self.assertIn(fg, patch)

    def test_NET07_a_partly_filled_star_fills_only_its_left_part(self):
        im = self.render(fractions=[0, 0, 0, 0, 0.5])
        fg = imaging.text_color_for((200, 60, 30))
        w = im.width * 0.8 / (5 + 4 * backface.STAR_GAP)
        cx = im.width * 0.1 + w / 2 + 4 * w * (1 + backface.STAR_GAP)
        best = max(range(im.height), key=lambda y: sum(im.getpixel((x, y)) == fg for x in range(int(cx - w), int(cx + w))))
        left = sum(im.getpixel((x, best)) == fg for x in range(int(cx - w / 2), int(cx)))
        right = sum(im.getpixel((x, best)) == fg for x in range(int(cx + 2), int(cx + w / 2)))
        self.assertGreater(left, right + 3)

    def test_NET07_text_and_stars_stay_inside_the_back(self):
        for text in ("Mar 5, 2026", "Sep 30, 2026"):
            im = self.render(date_text=text, fractions=[1, 1, 1, 1, 1])
            bg = (200, 60, 30)
            xs = [x for x in range(im.width) for y in range(im.height) if im.getpixel((x, y)) != bg]
            self.assertGreaterEqual(min(xs), im.width * 0.05)
            self.assertLessEqual(max(xs), im.width * 0.95)

    def test_NET07_date_text_is_drawn_when_given(self):
        a = self.render(date_text="Mar 5, 2026")
        self.assertGreater(len(a.getcolors(1000)), 1)

    # ---- through the net ----
    def book(self, **kw):
        return c.Book(title="Hyperion", authors=["Dan Simmons"], rating=kw.get("rating", 4.0),
                      read_date=kw.get("date", c.ReadDate(2026, 3, 5)))

    def back_of(self, r):
        return r.image.crop((0, 0, r.back_w_px, r.image.height))

    def test_NET07_details_back_is_the_complement_colour_with_extras(self):
        s = S.Settings(back_style="details")
        r = net.build_net(self.book(), fake_cover("a"), s)
        plain = net.build_net(self.book(), fake_cover("a"), S.Settings(back_style="complement"))
        self.assertNotEqual(self.back_of(r).tobytes(), self.back_of(plain).tobytes())
        bg = self.back_of(plain).getpixel((2, 2))
        self.assertEqual(self.back_of(r).getpixel((2, 2)), bg)             # same background colour

    def test_NET07_each_part_can_be_switched_off(self):
        def back(**kw):
            return self.back_of(net.build_net(self.book(), fake_cover("a"), S.Settings(back_style="details", **kw)))
        plain = self.back_of(net.build_net(self.book(), fake_cover("a"), S.Settings(back_style="complement")))
        both = back()
        date_only = back(back_show_rating=False)
        stars_only = back(back_show_date=False)
        neither = back(back_show_date=False, back_show_rating=False)
        self.assertEqual(neither.tobytes(), plain.tobytes())
        for im in (both, date_only, stars_only):
            self.assertNotEqual(im.tobytes(), plain.tobytes())
        self.assertEqual(len({both.tobytes(), date_only.tobytes(), stars_only.tobytes()}), 3)

    def test_NET07_date_format_setting_changes_the_text(self):
        def back(f):
            return self.back_of(net.build_net(self.book(), fake_cover("a"),
                                              S.Settings(back_style="details", back_show_rating=False,
                                                         back_date_format=f))).tobytes()
        self.assertEqual(len({back("full"), back("month"), back("year")}), 3)

    def test_NET07_books_without_rating_or_date_skip_those_parts(self):
        s = S.Settings(back_style="details")
        plain = self.back_of(net.build_net(self.book(), fake_cover("a"), S.Settings(back_style="complement")))
        bare = c.Book(title="Hyperion", authors=["Dan Simmons"])
        self.assertEqual(self.back_of(net.build_net(bare, fake_cover("a"), s)).tobytes(), plain.tobytes())
        no_rating = self.back_of(net.build_net(self.book(rating=None), fake_cover("a"), s))
        with_rating = self.back_of(net.build_net(self.book(), fake_cover("a"), s))
        self.assertNotEqual(no_rating.tobytes(), with_rating.tobytes())

    def test_NET07_front_and_spine_are_unaffected(self):
        a = net.build_net(self.book(), fake_cover("a"), S.Settings(back_style="details"))
        b = net.build_net(self.book(), fake_cover("a"), S.Settings(back_style="complement"))
        self.assertEqual(a.image.crop((a.back_w_px, 0, a.image.width, a.image.height)).tobytes(),
                         b.image.crop((b.back_w_px, 0, b.image.width, b.image.height)).tobytes())

    def test_NET07_settings_validation(self):
        self.assertEqual(S.Settings(back_style="details").validate(), [])
        self.assertTrue(S.Settings(back_date_format="weird").validate())

    def test_NET07_the_option_survives_save_and_load(self):
        p = Path(tempfile.mkdtemp()) / "s.json"
        S.save_settings(S.Settings(back_style="details", back_show_date=False, back_date_format="year"), p)
        s = S.load_settings(p)
        self.assertEqual((s.back_style, s.back_show_date, s.back_show_rating, s.back_date_format),
                         ("details", False, True, "year"))


class TestSettingsExportImport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def ctl(self, name="a", **kw):
        from minibook.controller import AppController
        return AppController(S.Settings(**kw), {}, None, settings_path=self.tmp / f"{name}.json",
                             prefs_path=self.tmp / f"{name}p.json", custom_dir=self.tmp / "cu",
                             edits_path=self.tmp / "e.json")

    def test_SET04_export_is_json_with_output_settings_only(self):
        import json
        text = self.ctl(google_api_key="SECRET", output_dir="/home/me/pdfs", height_mm=40.0).export_settings()
        data = json.loads(text)
        self.assertEqual(data["format"], "minibook-settings")
        self.assertEqual(data["settings"]["height_mm"], 40.0)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("/home/me/pdfs", text)
        for k in ("google_api_key", "output_dir", "version"):
            self.assertNotIn(k, data["settings"])

    def test_SET04_round_trip_between_two_installs(self):
        a = self.ctl("a", height_mm=50.0, width_mm=30.0, thickness_mm=8.0, back_style="details",
                     back_date_format="year", spine_wrap=True, paper="a4", unit="mm", gutter_mm=6.0)
        b = self.ctl("b", google_api_key="MINE", output_dir="/my/folder")
        res = b.import_settings(a.export_settings())
        self.assertIsNotNone(res.settings)
        self.assertEqual(res.problems, [])
        for k in ("height_mm", "width_mm", "thickness_mm", "back_style", "back_date_format", "spine_wrap",
                  "paper", "unit", "gutter_mm"):
            self.assertEqual(getattr(b.settings, k), getattr(a.settings, k), k)
        self.assertEqual(b.settings.google_api_key, "MINE")          # kept
        self.assertEqual(b.settings.output_dir, "/my/folder")        # kept

    def test_SET04_import_is_saved_like_any_other_change(self):
        a = self.ctl("a", height_mm=50.0, width_mm=30.0)
        b = self.ctl("b")
        b.import_settings(a.export_settings())
        self.assertEqual(S.load_settings(self.tmp / "b.json").height_mm, 50.0)

    def test_SET04_a_key_inside_a_file_is_ignored(self):
        import json
        data = json.loads(self.ctl().export_settings())
        data["settings"]["google_api_key"] = "FROM-FILE"
        data["settings"]["output_dir"] = "/elsewhere"
        b = self.ctl("b", google_api_key="MINE")
        res = b.import_settings(json.dumps(data))
        self.assertEqual(b.settings.google_api_key, "MINE")
        self.assertEqual(b.settings.output_dir, "")
        self.assertTrue(any("google_api_key" in x for x in res.ignored))

    def test_SET04_unknown_and_wrong_typed_entries_are_listed_and_the_rest_applied(self):
        import json
        data = json.loads(self.ctl().export_settings())
        data["settings"]["colour_of_the_moon"] = "green"
        data["settings"]["height_mm"] = "tall"
        data["settings"]["thickness_mm"] = 9.0
        b = self.ctl("b")
        before_height = b.settings.height_mm
        res = b.import_settings(json.dumps(data))
        self.assertEqual(b.settings.thickness_mm, 9.0)
        self.assertEqual(b.settings.height_mm, before_height)
        self.assertTrue(any("colour_of_the_moon" in x for x in res.ignored))
        self.assertTrue(any("height_mm" in x for x in res.ignored))

    def test_SET04_files_that_are_not_settings_files_change_nothing(self):
        b = self.ctl("b")
        before = b.settings
        for junk in (b"not json at all", b"[1, 2, 3]", b'{"hello": "world"}', b'{"format": "other", "settings": {}}'):
            res = b.import_settings(junk)
            self.assertIsNone(res.settings)
            self.assertTrue(res.problems)
            self.assertEqual(b.settings, before)

    def test_SET04_settings_that_cannot_print_are_refused_whole(self):
        import json
        data = json.loads(self.ctl().export_settings())
        data["settings"]["height_mm"] = 900.0                      # does not fit on any page
        data["settings"]["thickness_mm"] = 9.0
        b = self.ctl("b")
        before = b.settings
        res = b.import_settings(json.dumps(data))
        self.assertIsNone(res.settings)
        self.assertTrue(any("fit" in p for p in res.problems))
        self.assertEqual(b.settings, before)                       # even the valid thickness was not applied

    def test_SET04_a_file_from_a_newer_app_is_refused(self):
        import json
        data = json.loads(self.ctl().export_settings())
        data["version"] = 99
        res = self.ctl("b").import_settings(json.dumps(data))
        self.assertIsNone(res.settings)
        self.assertTrue(any("newer" in p for p in res.problems))

    def test_SET04_switching_between_two_book_sizes(self):
        small = self.ctl("s", height_mm=19.05, width_mm=12.7, unit="mm")
        big = self.ctl("l", height_mm=45.0, width_mm=30.0, thickness_mm=8.0)
        me = self.ctl("me")
        me.import_settings(small.export_settings())
        self.assertEqual(me.settings.height_mm, 19.05)
        me.import_settings(big.export_settings())
        self.assertEqual((me.settings.height_mm, me.settings.thickness_mm), (45.0, 8.0))

    def test_SET04_utf8_bom_files_are_accepted(self):
        text = self.ctl(height_mm=50.0, width_mm=30.0).export_settings().encode("utf-8-sig")
        b = self.ctl("b")
        self.assertIsNotNone(b.import_settings(text).settings)
        self.assertEqual(b.settings.height_mm, 50.0)


class TestPreviewEngine(unittest.TestCase):
    def setUp(self):
        from minibook import preview
        self.pv = preview
        self.books = [c.Book(title=f"Book {i}", authors=[f"Author {i}"], rating=3.5,
                             read_date=c.ReadDate(2026, 1, i + 1)) for i in range(40)]
        self.covers = [fake_cover(str(i), 600, 900) for i in range(40)]
        self.items = [self.pv.PreviewInput(b, im) for b, im in zip(self.books, self.covers)]
        self.e = self.pv.PreviewEngine()
        self.s = S.Settings()

    def test_EXP07_page_is_the_paper_size_at_preview_resolution(self):
        p = self.e.render_page(self.items, self.s)
        w, h = S.PAPERS_MM["letter"]
        self.assertEqual(p.image.size, (round(w / 25.4 * self.pv.PREVIEW_DPI), round(h / 25.4 * self.pv.PREVIEW_DPI)))
        a4 = self.e.render_page(self.items, S.Settings(paper="a4"))
        self.assertGreater(a4.image.height, p.image.height)

    def test_EXP07_only_the_visible_page_is_built(self):
        p = self.e.render_page(self.items, self.s, 0)
        self.assertEqual((p.books_on_page, p.pages, p.per_page, p.nets_built), (28, 2, 28, 28))
        q = self.e.render_page(self.items, self.s, 1)
        self.assertEqual((q.books_on_page, q.nets_built), (12, 12))

    def test_EXP07_page_numbers_are_clamped(self):
        self.assertEqual(self.e.render_page(self.items, self.s, 99).page, 1)
        self.assertEqual(self.e.render_page(self.items, self.s, -5).page, 0)

    def test_EXP07_layout_only_changes_reuse_every_wrap(self):
        self.e.render_page(self.items, self.s)
        for change in ({"paper": "a4"}, {"margin_mm": 10.0}, {"gutter_mm": 6.0}, {"fold_marks": False}):
            s2 = S.Settings(**change)
            p = self.e.render_page(self.items, s2)
            self.assertEqual((p.nets_built, p.nets_reused), (0, p.books_on_page), change)

    def test_EXP07_settings_that_change_a_wrap_redraw_only_wraps(self):
        self.e.render_page(self.items, self.s)
        for change in ({"back_style": "complement"}, {"spine_wrap": True}, {"thickness_mm": 8.0},
                       {"spine_min_font_pt": 5.0}, {"back_show_date": False}):
            if "back_show_date" in change:
                base = S.Settings(back_style="details")
                self.e.render_page(self.items, base)
                s2 = S.Settings(back_style="details", **change)
            else:
                s2 = S.Settings(**change)
            p = self.e.render_page(self.items, s2)
            self.assertEqual(p.nets_built, p.books_on_page, change)

    def test_EXP07_a_new_cover_or_crop_redraws_just_that_book(self):
        self.e.render_page(self.items, self.s)
        self.items[3] = self.pv.PreviewInput(self.books[3], fake_cover("new", 600, 900))
        self.items[5] = self.pv.PreviewInput(self.books[5], self.covers[5], zoom=1.5)
        p = self.e.render_page(self.items, self.s)
        self.assertEqual((p.nets_built, p.nets_reused), (2, 26))

    def test_EXP07_editing_a_title_redraws_just_that_book(self):
        self.e.render_page(self.items, self.s)
        self.books[7].title = "Renamed"
        p = self.e.render_page(self.items, self.s)
        self.assertEqual(p.nets_built, 1)

    def test_EXP07_the_preview_pixels_change_when_a_setting_changes(self):
        a = self.e.render_page(self.items, self.s).image.tobytes()
        b = self.e.render_page(self.items, S.Settings(back_style="complement")).image.tobytes()
        self.assertNotEqual(a, b)
        self.assertEqual(a, self.e.render_page(self.items, self.s).image.tobytes())      # and is stable

    def test_EXP07_stale_work_is_abandoned(self):
        calls = {"n": 0}

        def current():
            calls["n"] += 1
            return calls["n"] < 5               # becomes stale part way through
        with self.assertRaises(self.pv.PreviewCancelled):
            self.pv.PreviewEngine(workers=1).render_page(self.items, self.s, is_current=current)

    def test_EXP07_a_cancelled_render_leaves_finished_wraps_in_the_cache(self):
        n = {"i": 0}

        def current():
            n["i"] += 1
            return n["i"] < 10
        e = self.pv.PreviewEngine(workers=1)
        with self.assertRaises(self.pv.PreviewCancelled):
            e.render_page(self.items, self.s, is_current=current)
        p = e.render_page(self.items, self.s)
        self.assertGreater(p.nets_reused, 0)

    def test_EXP07_invalid_settings_raise_a_readable_error(self):
        from minibook import layout
        with self.assertRaises(layout.LayoutError):
            self.e.render_page(self.items, S.Settings(gutter_mm=0.1))

    def test_EXP07_cache_is_bounded(self):
        e = self.pv.PreviewEngine()
        many = [self.pv.PreviewInput(c.Book(title=f"T{i}", authors=["A"]), None) for i in range(self.pv.MAX_CACHED_NETS + 60)]
        for k in range(0, len(many), 28):
            e.render_page(many, self.s, k // 28)
        self.assertLessEqual(len(e._nets), self.pv.MAX_CACHED_NETS)

    def test_EXP07_nets_are_positioned_like_the_pdf(self):
        from minibook import layout
        s = self.s
        p = self.e.render_page(self.items, s)
        grid = layout.make_grid(*s.page_mm, s.net_width_mm, s.height_mm, s.gutter_mm, s.margin_mm)
        px = self.pv.PREVIEW_DPI / 25.4
        cell = grid.cell(5)
        x0, y0 = round(cell.x_mm * px), round(cell.y_mm * px)
        w, h = round(cell.w_mm * px), round(cell.h_mm * px)
        area = p.image.crop((x0, y0, x0 + w, y0 + h))
        self.assertNotEqual(len(area.getcolors(100000)), 1)               # artwork is there
        for (cx, cy) in ((x0 - 3, y0 + h // 2), (x0 + w + 3, y0 + h // 2)):
            self.assertEqual(p.image.getpixel((cx, cy)), (255, 255, 255))   # gutters are clear

    def test_EXP07_marks_are_drawn_outside_the_artwork(self):
        from minibook import layout
        p = self.e.render_page(self.items[:1], self.s)
        px = self.pv.PREVIEW_DPI / 25.4
        cell = layout.make_grid(*self.s.page_mm, self.s.net_width_mm, self.s.height_mm,
                                self.s.gutter_mm, self.s.margin_mm).cell(0)
        x0, y0 = round(cell.x_mm * px), round(cell.y_mm * px)
        w, h = round(cell.w_mm * px), round(cell.h_mm * px)
        blacks = [(x, y) for x in range(p.image.width) for y in range(p.image.height)
                  if p.image.getpixel((x, y)) == (0, 0, 0)]
        self.assertTrue(blacks)
        outside = [(x, y) for (x, y) in blacks if not (x0 <= x < x0 + w and y0 <= y < y0 + h)]
        self.assertGreater(len(outside), 0)
        fold = [pt for pt in outside if y0 > pt[1]]
        self.assertTrue(fold)
        off = self.e.render_page(self.items[:1], S.Settings(fold_marks=False)).image
        n_off = sum(off.getpixel((x, y)) == (0, 0, 0) for x in range(off.width) for y in range(off.height))
        self.assertLess(n_off, len(blacks))

    def test_EXP07_preview_matches_the_pdf(self):
        import shutil, subprocess
        from minibook import pdfexport
        if not shutil.which("pdftoppm"):
            self.skipTest("pdftoppm not available")
        from PIL import ImageChops, ImageStat
        s = self.s
        out = Path(tempfile.mkdtemp())
        nets = [net.build_net(it.book, it.image, s) for it in self.items[:28]]
        pdfexport.export_pdf(nets, s, out / "p.pdf")
        subprocess.run(["pdftoppm", "-r", str(self.pv.PREVIEW_DPI), "-png", "-f", "1", "-l", "1",
                        str(out / "p.pdf"), str(out / "p")], check=True)
        ref = Image.open(next(out.glob("p*.png"))).convert("L")
        mine = self.e.render_page(self.items[:28], s).image.convert("L")
        self.assertLessEqual(abs(ref.width - mine.width), 2)
        ref = ref.resize(mine.size)
        diff = ImageStat.Stat(ImageChops.difference(ref, mine)).mean[0]
        self.assertLess(diff, 6.0)                        # same sheet, within resampling noise

    def test_EXP07_cold_page_is_fast_enough_and_warm_changes_are_nearly_free(self):
        import time
        t = time.perf_counter()
        self.e.render_page(self.items, self.s)
        cold = time.perf_counter() - t
        t = time.perf_counter()
        self.e.render_page(self.items, S.Settings(margin_mm=10.0))
        warm = time.perf_counter() - t
        self.assertLess(cold, 5.0)
        self.assertLess(warm, 0.5)
        self.assertLess(warm, cold)


class TestControllerPreview(unittest.TestCase):
    def setUp(self):
        from minibook.controller import AppController
        from tests.helpers import REAL_CSV
        self.tmp = Path(tempfile.mkdtemp())
        self.ctl = AppController(S.Settings(), {}, None, settings_path=self.tmp / "s.json",
                                 prefs_path=self.tmp / "p.json", custom_dir=self.tmp / "cu",
                                 edits_path=self.tmp / "e.json", persist=False)
        self.ctl.load_csv(REAL_CSV.read_bytes(), "x.csv")

    def test_EXP07_preview_follows_the_selection(self):
        p = self.ctl.preview_page()
        self.assertEqual(p.books_on_page, 28)
        self.assertEqual(p.pages, 2)
        self.ctl.select_all(False)
        self.assertIsNone(self.ctl.preview_page())
        self.ctl.set_selected(self.ctl.dated[0].id, True)
        self.assertEqual(self.ctl.preview_page().books_on_page, 1)

    def test_EXP07_preview_uses_the_current_cover_and_crop(self):
        b = self.ctl.dated[0]
        self.ctl.select_all(False)
        self.ctl.set_selected(b.id, True)
        first = self.ctl.preview_page().image.tobytes()
        st = self.ctl.state(b)
        st.image, st.searched = fake_cover("zzz", 600, 900), True
        second = self.ctl.preview_page().image.tobytes()
        self.assertNotEqual(first, second)
        self.ctl.set_crop(b, zoom=2.0)
        self.assertNotEqual(second, self.ctl.preview_page().image.tobytes())

    def test_EXP07_settings_changes_are_picked_up(self):
        self.ctl.preview_page()
        self.ctl.update_settings(paper="a4")
        p = self.ctl.preview_page()
        self.assertEqual(p.nets_built, 0)
        self.ctl.update_settings(back_style="details")
        self.assertEqual(self.ctl.preview_page().nets_built, 28)


if __name__ == "__main__":
    unittest.main()


class TestHitTest(TestControllerPreview):
    def test_EXP07b_click_inside_a_wrap_finds_that_book(self):
        eng, s = self.ctl.preview, self.ctl.settings
        grid = eng.grid_for(s)
        px = eng.dpi / 25.4
        books = self.ctl.selected_books()
        for i in (0, 5, grid.per_page - 1):
            cell = grid.cell(i)
            x, y = (cell.x_mm + cell.w_mm / 2) * px, (cell.y_mm + cell.h_mm / 2) * px
            self.assertIs(self.ctl.preview_book_at(0, x, y), books[i])

    def test_EXP07b_second_page_maps_to_later_books(self):
        eng, s = self.ctl.preview, self.ctl.settings
        grid = eng.grid_for(s)
        px = eng.dpi / 25.4
        cell = grid.cell(0)
        x, y = (cell.x_mm + 1) * px, (cell.y_mm + 1) * px
        self.assertIs(self.ctl.preview_book_at(1, x, y), self.ctl.selected_books()[grid.per_page])

    def test_EXP07b_click_on_empty_paper_or_unused_cell_finds_nothing(self):
        self.assertIsNone(self.ctl.preview_book_at(0, 1, 1))              # the page corner
        self.assertIsNone(self.ctl.preview_book_at(0, -5, 10))
        self.ctl.select_all(False)
        self.ctl.set_selected(self.ctl.dated[0].id, True)
        eng, s = self.ctl.preview, self.ctl.settings
        cell = eng.grid_for(s).cell(3)                                    # no fourth book on the page
        px = eng.dpi / 25.4
        self.assertIsNone(self.ctl.preview_book_at(0, (cell.x_mm + 1) * px, (cell.y_mm + 1) * px))


class TestBackMatchesSpine(unittest.TestCase):
    def book(self):
        return Book("Dune", ["Frank Herbert"], rating=4.0, read_date=ReadDate(2026, 3, 5))

    def check(self, style, cover):
        r = net.build_net(self.book(), cover, S.Settings(back_style=style))
        back_px = r.image.getpixel((2, 2))
        spine_px = r.image.getpixel((r.back_w_px + 2, 2))
        self.assertEqual(back_px, spine_px)
        return back_px

    def test_NET02_solid_back_is_exactly_the_spine_colour(self):
        self.check("complement", Image.new("RGB", (400, 600), (20, 120, 40)))
        self.assertEqual(self.check("complement", Image.new("RGB", (400, 600), (200, 30, 30))), (200, 30, 30))

    def test_NET07_details_back_is_the_spine_colour_too(self):
        self.assertEqual(self.check("details", Image.new("RGB", (400, 600), (20, 120, 40))), (20, 120, 40))

    def test_NET02_zoomed_out_bars_spine_and_back_all_share_one_colour(self):
        wide = Image.new("RGB", (900, 300), (60, 60, 200))
        r = net.build_net(self.book(), wide, S.Settings(back_style="complement"), zoom=0.1)
        self.assertEqual(r.image.getpixel((2, 2)), r.image.getpixel((r.back_w_px + 2, 2)))

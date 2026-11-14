"""IMG-*, NET-*, EXP-*, DIM-06, TST-03: cropping, spine, net, layout, PDF, covers."""
import tempfile
import unittest
from pathlib import Path

import pdfplumber
from PIL import Image

from minibook import covers, csvimport as c, imaging, layout, net, pdfexport, settings as S, spine, units
from tests.helpers import REAL_CSV, FakeHttp, fake_cover, json_bytes, png_bytes


class TestImaging(unittest.TestCase):
    def test_IMG08_default_is_center_crop(self):
        w = imaging.crop_window(1000, 1000, 0.5)
        self.assertAlmostEqual(w.left + w.width / 2, 500)
        self.assertAlmostEqual(w.height, 1000)
        self.assertAlmostEqual(w.width, 500)

    def test_IMG09_zoom_and_pan_stay_inside_image(self):
        for zoom in (1, 1.5, 3):
            for pan in (0, 0.5, 1):
                l, t, r, b = imaging.crop_window(400, 600, 0.5, zoom, pan, pan).box
                self.assertGreaterEqual(l, -1e-9); self.assertGreaterEqual(t, -1e-9)
                self.assertLessEqual(r, 400 + 1e-9); self.assertLessEqual(b, 600 + 1e-9)

    def test_IMG09_aspect_locked(self):
        w = imaging.crop_window(731, 1093, 0.5, 2.2, 0.3, 0.8)
        self.assertAlmostEqual(w.width / w.height, 0.5)

    def test_IMG09_pan_moves_window(self):
        a = imaging.crop_window(1000, 1000, 0.5, 1, 0.0, 0.5)
        b = imaging.crop_window(1000, 1000, 0.5, 1, 1.0, 0.5)
        self.assertLess(a.left, b.left)

    def test_IMG08_output_is_exact_size(self):
        out = imaging.crop_to_board(fake_cover("a", 333, 777), 150, 225)
        self.assertEqual(out.size, (150, 225))

    def test_IMG06_square_art_loses_a_third(self):
        self.assertAlmostEqual(imaging.crop_loss(1000, 1000, 2 / 3), 1 / 3, places=3)
        self.assertGreater(imaging.crop_loss(1000, 1000, 2 / 3), imaging.CROP_LOSS_WARN)
        self.assertAlmostEqual(imaging.crop_loss(400, 600, 2 / 3), 0.0, places=3)

    def test_IMG05_quality_is_judged_against_print_size(self):
        # board is 12.7 mm (0.5 in) wide, 19.05 mm (0.75 in) tall; 300 dpi needs 150 x 225 px
        mm_w, mm_h = 12.7, 19.05
        self.assertEqual(imaging.quality(150, 225, mm_w, mm_h, 300)[0], "good")
        self.assertEqual(imaging.quality(110, 165, mm_w, mm_h, 300)[0], "ok")
        self.assertEqual(imaging.quality(60, 90, mm_w, mm_h, 300)[0], "low")
        # the same small image is fine for a smaller print
        self.assertEqual(imaging.quality(150, 225, mm_w, mm_h, 150)[0], "good")

    def test_IMG05_zoom_reduces_effective_dpi(self):
        self.assertLess(imaging.effective_dpi(400, 600, 12.7, 19.05, 2.0),
                        imaging.effective_dpi(400, 600, 12.7, 19.05, 1.0))

    def test_NET02_complement_is_opposite_hue_and_not_muddy(self):
        r, g, b = imaging.complement((200, 30, 30))
        self.assertGreater(g, 100); self.assertGreater(b, 100); self.assertLess(r, g)
        for col in [(0, 0, 0), (255, 255, 255), (128, 128, 128)]:
            comp = imaging.complement(col)
            self.assertGreater(max(comp), 80)

    def test_NET03_text_color_contrasts(self):
        for bg in [(0, 0, 0), (255, 255, 255), (200, 30, 30), (30, 60, 200), (240, 220, 80), (100, 100, 100)]:
            fg = imaging.text_color_for(bg)
            self.assertGreaterEqual(imaging.contrast_ratio(bg, fg), 3.0, bg)

    def test_NET03_dominant_color_picks_the_main_color(self):
        im = Image.new("RGB", (100, 100), (20, 120, 40))
        im.paste((255, 255, 255), (0, 0, 20, 20))
        r, g, b = imaging.dominant_color(im)
        self.assertGreater(g, r); self.assertGreater(g, b)


class TestSpine(unittest.TestCase):
    DPI = 300

    def _fit(self, title, author="Some Author", length=225, thick=75, **kw):
        return spine.fit_text(title, author, length, thick, self.DPI, **kw)

    def test_NET05_never_overflows_any_real_title(self):
        books = c.parse_storygraph(REAL_CSV)
        for b in books:
            img, info = spine.render_spine(b.title, b.author, 75, 225, self.DPI, (230, 230, 230))
            diff = Image.eval(img.convert("L"), lambda p: 255 if p < 200 else 0).getbbox()
            if diff:
                pad_px = int(spine.SAFE_PAD_MM / 25.4 * self.DPI) - 3
                self.assertGreaterEqual(diff[1], pad_px, b.title)
                self.assertLessEqual(diff[3], 225 - pad_px, b.title)
                self.assertGreaterEqual(diff[0], 0)
                self.assertLessEqual(diff[2], 75)

    def test_NET05_never_overflows_on_a_very_thin_spine(self):
        for title in ["The Great Book of Amber: The Complete Amber Chronicles, 1-10", "Eric", "A" * 120]:
            img, info = spine.render_spine(title, "Roger Zelazny", 20, 150, self.DPI, (240, 240, 240))
            self.assertEqual(img.size, (20, 150))
            self.assertTrue(info.title)

    def test_NET05_author_shrinks_then_drops_then_title_shrinks(self):
        roomy = self._fit("Eric", length=900)
        self.assertEqual(roomy.author, "Some Author")
        tight = self._fit("Eric", length=130)
        self.assertIsNone(tight.author)
        self.assertIn("author dropped (does not fit)", tight.warnings)
        # with the author gone the title may only shrink, never exceed the roomy size
        self.assertLessEqual(tight.title_pt, roomy.title_pt)

    def test_NET05_long_title_is_truncated_with_ellipsis_and_flagged(self):
        info = self._fit("A" * 80, length=150)
        self.assertTrue(info.title.endswith(spine.ELLIPSIS))
        self.assertIn("title truncated", info.warnings)

    def test_NET06_hide_author(self):
        info = self._fit("Eric", length=900, hide_author=True)
        self.assertIsNone(info.author)
        self.assertNotIn("author dropped (does not fit)", info.warnings)

    def test_NET06_drop_subtitle(self):
        t = "The Food Lab: Better Home Cooking Through Science"
        self.assertEqual(spine.shorten_title(t, True), "The Food Lab")
        self.assertEqual(spine.shorten_title(t, False), t)
        self.assertEqual(self._fit(t, length=900, drop_subtitle=True).title, "The Food Lab")

    def test_NET06_minimum_font_size_is_flagged_and_respected(self):
        info = self._fit("Tress of the Emerald Sea", length=225, min_font_pt=4.0)
        self.assertGreaterEqual(info.title_pt, 4.0 - 0.2)
        big = self._fit("Tress of the Emerald Sea", length=225, min_font_pt=9.0)
        self.assertIn("title truncated", big.warnings)

    def test_NET04_reverse_option_flips_reading_direction(self):
        from PIL import ImageChops
        down, _ = spine.render_spine("Hyperion", "", 75, 225, self.DPI, (255, 255, 255))
        up, _ = spine.render_spine("Hyperion", "", 75, 225, self.DPI, (255, 255, 255), reverse=True)
        self.assertNotEqual(down.tobytes(), up.tobytes())
        # reversed text is the default rotated half a turn
        diff = ImageChops.difference(down.transpose(Image.Transpose.ROTATE_180), up)
        self.assertLessEqual(max(diff.getextrema()[0][1], diff.getextrema()[1][1]), 3)

    def test_NET04_text_is_actually_vertical(self):
        img, _ = spine.render_spine("Hyperion", "", 75, 225, self.DPI, (255, 255, 255))
        bbox = Image.eval(img.convert("L"), lambda p: 255 if p < 128 else 0).getbbox()
        self.assertGreater(bbox[3] - bbox[1], bbox[2] - bbox[0])   # taller than wide

    def test_NET04_spine_is_the_requested_size(self):
        img, _ = spine.render_spine("Mort", "Terry Pratchett", 75, 225, self.DPI, (10, 10, 10))
        self.assertEqual(img.size, (75, 225))

    def test_bundled_font_exists(self):
        self.assertTrue(Path(spine.font_path(True)).exists())
        self.assertTrue(Path(spine.font_path(False)).exists())


class TestNet(unittest.TestCase):
    def setUp(self):
        self.book = c.Book(title="Hyperion", authors=["Dan Simmons"])
        self.s = S.Settings()

    def test_NET01_panel_sizes_at_300dpi(self):
        r = net.build_net(self.book, fake_cover("h"), self.s)
        self.assertEqual((r.back_w_px, r.spine_w_px, r.front_w_px), (225, 75, 225))   # 0.75 / 0.25 / 0.75 in at 300 dpi
        self.assertEqual(r.image.size, (525, 375))                   # 1.75 x 1.25 in

    def test_NET01_panel_order_back_spine_front(self):
        src = Image.new("RGB", (400, 600), (200, 20, 20))
        r = net.build_net(self.book, src, self.s)
        px = r.image.load()
        self.assertEqual(px[10, 100], (200, 20, 20))     # back
        self.assertEqual(px[525 - 10, 100], (200, 20, 20))  # front

    def test_NET02_back_is_an_identical_copy_not_mirrored(self):
        src = Image.new("RGB", (400, 600), (240, 240, 240))
        for x in range(0, 200):
            for y in range(0, 600):
                src.putpixel((x, y), (10, 10, 200))  # left half blue, right half grey: asymmetric
        r = net.build_net(self.book, src, self.s)
        back = r.image.crop((0, 0, 225, 375))
        front = r.image.crop((300, 0, 525, 375))
        self.assertEqual(back.tobytes(), front.tobytes())
        self.assertNotEqual(back.tobytes(), back.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes())

    def test_NET02_complement_back_is_one_solid_color(self):
        self.s.back_style = "complement"
        r = net.build_net(self.book, fake_cover("h"), self.s)
        back = r.image.crop((0, 0, 225, 375))
        self.assertEqual(len(back.getcolors()), 1)
        front = r.image.crop((300, 0, 525, 375))
        self.assertNotEqual(back.tobytes(), front.tobytes())

    def test_NET03_spine_background_matches_cover(self):
        src = Image.new("RGB", (400, 600), (20, 120, 40))
        r = net.build_net(self.book, src, self.s)
        self.assertEqual(r.image.getpixel((225 + 2, 2)), (20, 120, 40))

    def test_IMG10_missing_cover_uses_placeholder_and_warns(self):
        r = net.build_net(self.book, None, self.s)
        self.assertEqual(r.image.size, (525, 375))
        self.assertTrue(any("no cover" in w for w in r.warnings))

    def test_IMG06_square_art_warns(self):
        r = net.build_net(self.book, fake_cover("sq", 1200, 1200), self.s)
        self.assertTrue(any("center crop discards" in w for w in r.warnings))
        r2 = net.build_net(self.book, fake_cover("sq", 1200, 1200), self.s, zoom=1.2)
        self.assertFalse(any("center crop discards" in w for w in r2.warnings))

    def test_IMG05_low_resolution_warns(self):
        r = net.build_net(self.book, fake_cover("lo", 60, 90), self.s)
        self.assertTrue(any("low resolution" in w for w in r.warnings))

    def test_DIM01_aspect_mode_changes_cover_width(self):
        s = S.Settings(size_mode="aspect", aspect=0.5, height_mm=19.05)
        r = net.build_net(self.book, fake_cover("a"), s)
        self.assertEqual(r.front_w_px, round(19.05 * 0.5 / 25.4 * 300))


class TestLayout(unittest.TestCase):
    def test_EXP05_grid_fits_and_is_centered(self):
        s = S.Settings()
        g = layout.make_grid(215.9, 279.4, s.net_width_mm, s.height_mm, s.gutter_mm, s.margin_mm)
        self.assertEqual((g.cols, g.rows), (4, 7))        # 1.75 x 1.25 in nets on Letter
        left = g.origin_x_mm
        right = 215.9 - (g.origin_x_mm + g.cols * g.net_w_mm + (g.cols - 1) * g.gutter_mm)
        self.assertAlmostEqual(left, right)

    def test_EXP05_cells_never_overlap_or_leave_page(self):
        g = layout.make_grid(210, 297, 31.75, 19.05, 4.0, 10.0)
        cells = [g.cell(i) for i in range(g.per_page)]
        for cell in cells:
            self.assertGreaterEqual(cell.x_mm, 10 - 1e-9); self.assertGreaterEqual(cell.y_mm, 10 - 1e-9)
            self.assertLessEqual(cell.x_mm + cell.w_mm, 210 - 10 + 1e-9)
            self.assertLessEqual(cell.y_mm + cell.h_mm, 297 - 10 + 1e-9)
        for a in cells:
            for b in cells:
                if a is b:
                    continue
                apart = (a.x_mm + a.w_mm + 4.0 - 1e-9 <= b.x_mm or b.x_mm + b.w_mm + 4.0 - 1e-9 <= a.x_mm or
                         a.y_mm + a.h_mm + 4.0 - 1e-9 <= b.y_mm or b.y_mm + b.h_mm + 4.0 - 1e-9 <= a.y_mm)
                self.assertTrue(apart)

    def test_EXP05_page_count(self):
        g = layout.make_grid(215.9, 279.4, 31.75, 19.05, 4.0, 10.0)
        self.assertEqual(layout.page_count(0, g), 0)
        self.assertEqual(layout.page_count(55, g), 1)
        self.assertEqual(layout.page_count(56, g), 2)

    def test_EXP02_gutter_enforced(self):
        with self.assertRaises(layout.LayoutError):
            layout.make_grid(215.9, 279.4, 31.75, 19.05, 1.0, 10.0)

    def test_EXP06_book_too_big_for_page(self):
        with self.assertRaises(layout.LayoutError):
            layout.make_grid(100, 100, 150, 19.05, 4.0, 10.0)

    def test_EXP03_marks_keep_clear_of_every_net(self):
        from minibook.settings import MARK_OFFSET_MM

        def dist_to_rect(x, y, cell):
            dx = max(cell.x_mm - x, 0, x - (cell.x_mm + cell.w_mm))
            dy = max(cell.y_mm - y, 0, y - (cell.y_mm + cell.h_mm))
            return (dx * dx + dy * dy) ** 0.5

        g = layout.make_grid(215.9, 279.4, 31.75, 19.05, 4.0, 10.0)
        cells = [g.cell(i) for i in range(g.per_page)]
        for cell in cells:
            marks = layout.cut_marks(cell, 4.0)
            self.assertEqual(len(marks), 8)
            for x1, y1, x2, y2 in marks:
                self.assertTrue(x1 == x2 or y1 == y2)            # axis-aligned
                for other in cells:                               # clear of this net AND its neighbours
                    for (x, y) in ((x1, y1), (x2, y2)):
                        self.assertGreaterEqual(dist_to_rect(x, y, other), MARK_OFFSET_MM - 1e-9)

    def test_EXP03_marks_in_a_gutter_do_not_touch_each_other(self):
        g = layout.make_grid(215.9, 279.4, 31.75, 19.05, 3.0, 10.0)   # tightest allowed gutter
        a, b = g.cell(0), g.cell(1)
        right_of_a = [m for m in layout.cut_marks(a, 3.0) if m[0] > a.x_mm + a.w_mm and m[1] == m[3]]
        left_of_b = [m for m in layout.cut_marks(b, 3.0) if m[0] < b.x_mm and m[1] == m[3]]
        reach_a = max(max(m[0], m[2]) for m in right_of_a)
        reach_b = min(min(m[0], m[2]) for m in left_of_b)
        self.assertGreaterEqual(reach_b - reach_a, 0.5 - 1e-9)   # a visible gap, not a bridge


class TestPdf(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _nets(self, n, s):
        return [net.build_net(c.Book(title=f"Book {i}", authors=["A B"]), fake_cover(str(i)), s) for i in range(n)]

    def _export(self, n, s):
        out = self.tmp / "o.pdf"
        grid = pdfexport.export_pdf(self._nets(n, s), s, out)
        return out, grid

    def test_DIM06_net_is_exact_physical_size(self):
        s = S.Settings()
        out, _ = self._export(3, s)
        with pdfplumber.open(out) as pdf:
            imgs = pdf.pages[0].images
            self.assertEqual(len(imgs), 3)
            want_w = units.mm_to_pt(s.net_width_mm)   # 2 x 0.75 in + 0.25 in = 1.75 in = 126 pt
            want_h = units.mm_to_pt(s.height_mm)      # 1.25 in = 90 pt
            self.assertAlmostEqual(want_w, 126.0, places=6)
            self.assertAlmostEqual(want_h, 90.0, places=6)
            for im in imgs:
                self.assertAlmostEqual(im["x1"] - im["x0"], want_w, delta=0.01)
                self.assertAlmostEqual(im["bottom"] - im["top"], want_h, delta=0.01)

    def test_DIM06_spine_measures_exactly_the_thickness_at_300dpi(self):
        s = S.Settings()
        r = net.build_net(c.Book(title="X"), fake_cover("x"), s)
        self.assertEqual(r.spine_w_px, 75)                 # 0.25 in at 300 dpi
        self.assertAlmostEqual(r.spine_w_px / 300, 0.25)

    def test_DIM06_exact_size_in_aspect_and_mm_modes(self):
        s = S.Settings(size_mode="aspect", aspect=2 / 3, height_mm=45.0, thickness_mm=8.0, unit="mm")
        out, _ = self._export(1, s)
        with pdfplumber.open(out) as pdf:
            im = pdf.pages[0].images[0]
            self.assertAlmostEqual(im["x1"] - im["x0"], units.mm_to_pt(2 * 30.0 + 8.0), delta=0.01)
            self.assertAlmostEqual(im["bottom"] - im["top"], units.mm_to_pt(45.0), delta=0.01)

    def test_EXP01_paper_sizes(self):
        for paper, (w, h) in (("letter", (612, 792)), ("a4", (595.276, 841.89))):
            out, _ = self._export(1, S.Settings(paper=paper))
            with pdfplumber.open(out) as pdf:
                self.assertAlmostEqual(pdf.pages[0].width, w, delta=0.1)
                self.assertAlmostEqual(pdf.pages[0].height, h, delta=0.1)

    def test_EXP05_pagination(self):
        s = S.Settings()
        out, grid = self._export(grid_n := 56, s)
        with pdfplumber.open(out) as pdf:
            self.assertEqual(len(pdf.pages), 2)
            self.assertEqual(len(pdf.pages[0].images), grid.per_page)
            self.assertEqual(len(pdf.pages[1].images), 56 - grid.per_page)

    def test_EXP03_cut_marks_are_present_and_never_touch_artwork(self):
        s = S.Settings()
        out, _ = self._export(12, s)
        with pdfplumber.open(out) as pdf:
            page = pdf.pages[0]
            lines = page.lines
            self.assertEqual(len(lines), 12 * (8 + 4))     # 8 cut marks + 4 fold marks per book
            boxes = [(i["x0"], i["top"], i["x1"], i["bottom"]) for i in page.images]
            min_clear = units.mm_to_pt(0.5) - 0.05
            for ln in lines:
                for (x, y) in ((ln["x0"], ln["top"]), (ln["x1"], ln["bottom"])):
                    for (bx0, by0, bx1, by1) in boxes:
                        dx = max(bx0 - x, 0, x - bx1)
                        dy = max(by0 - y, 0, y - by1)
                        self.assertGreaterEqual((dx * dx + dy * dy) ** 0.5, min_clear)
            for ln in lines:
                self.assertGreaterEqual(ln["x0"], 0); self.assertLessEqual(ln["x1"], page.width)
                self.assertGreaterEqual(ln["top"], 0); self.assertLessEqual(ln["bottom"], page.height)

    def test_EXP03_no_outline_rectangles_or_extra_graphics(self):
        out, _ = self._export(4, S.Settings())
        with pdfplumber.open(out) as pdf:
            self.assertEqual(pdf.pages[0].rects, [])
            self.assertEqual(pdf.pages[0].curves, [])

    def test_EXP02_adjustable_gutter_changes_spacing(self):
        gaps = []
        for gutter in (4.0, 8.0):
            out, _ = self._export(2, S.Settings(gutter_mm=gutter))
            with pdfplumber.open(out) as pdf:
                a, b = sorted(pdf.pages[0].images, key=lambda i: i["x0"])[:2]
                gaps.append(b["x0"] - a["x1"])
        self.assertAlmostEqual(gaps[0], units.mm_to_pt(4.0), delta=0.05)
        self.assertAlmostEqual(gaps[1], units.mm_to_pt(8.0), delta=0.05)

    def test_EXP04_a_sticker_safe_margin_moves_the_grid_in(self):
        s = S.Settings(margin_mm=6.35)
        out, grid = self._export(2, s)
        self.assertGreaterEqual(grid.origin_y_mm, 6.35)

    def test_invalid_settings_do_not_produce_a_pdf(self):
        with self.assertRaises(layout.LayoutError):
            pdfexport.export_pdf(self._nets(1, S.Settings()), S.Settings(gutter_mm=1.0), self.tmp / "x.pdf")
        with self.assertRaises(ValueError):
            pdfexport.export_pdf([], S.Settings(), self.tmp / "y.pdf")

    def test_IMG10_one_failed_book_does_not_stop_the_export(self):
        s = S.Settings()
        nets = [net.build_net(c.Book(title="ok"), fake_cover("1"), s),
                net.build_net(c.Book(title="no cover"), None, s)]
        out = self.tmp / "z.pdf"
        pdfexport.export_pdf(nets, s, out)
        with pdfplumber.open(out) as pdf:
            self.assertEqual(len(pdf.pages[0].images), 2)


class TestCovers(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        self.book = c.Book(title="Hyperion", authors=["Dan Simmons"], isbn="9780399178610", format="paperback")
        self.routes = {
            "covers.openlibrary.org/b/isbn/9780399178610": (200, png_bytes(600, 900, (200, 10, 10))),
            "openlibrary.org/search.json": (200, json_bytes({"docs": [
                {"title": "Hyperion", "cover_i": 111, "first_publish_year": 1989},
                {"title": "Hyperion (alt)", "cover_i": 222, "first_publish_year": 2005},
                {"title": "No cover edition"}]})),
            "covers.openlibrary.org/b/id/111": (200, png_bytes(300, 450, (10, 200, 10))),
            "covers.openlibrary.org/b/id/222": (200, png_bytes(120, 180, (10, 10, 200))),
            "googleapis.com/books/v1/volumes": (200, json_bytes({"items": [
                {"volumeInfo": {"title": "Hyperion", "publishedDate": "2011-05-01",
                                "imageLinks": {"thumbnail": "http://books.google.com/x?id=1&edge=curl"}}},
                {"volumeInfo": {"title": "No image"}}]})),
            "books.google.com/x": (200, png_bytes(128, 190, (200, 200, 10))),
        }

    def routes_with(self, overrides):
        """Overrides must come first (the fake network uses the first matching route)
        and must replace, not sit beside, the original entries for the same URL."""
        merged = dict(overrides)
        merged.update({k: v for k, v in self.routes.items() if k not in overrides})
        return merged

    def service(self, routes=None, **kw):
        self.http = FakeHttp(self.routes if routes is None else routes)
        return covers.CoverService(self.http, self.cache, **kw)

    def test_IMG01_isbn_match_comes_first_then_title_results(self):
        res = self.service().find_covers(self.book)
        self.assertEqual(res.errors, [])
        self.assertIn("isbn", res.candidates[0].url)
        sources = {cand.source for cand in res.candidates}
        self.assertEqual(sources, {"Open Library", "Google Books"})
        self.assertEqual(len(res.candidates), 4)

    def test_IMG01_google_urls_are_upgraded_to_https(self):
        res = self.service().search(self.book)
        g = [x for x in res.candidates if x.source == "Google Books"][0]
        self.assertTrue(g.url.startswith("https://"))
        self.assertNotIn("edge=curl", g.url)

    def test_IMG04_candidates_report_pixel_size(self):
        res = self.service().find_covers(self.book)
        self.assertEqual(res.candidates[0].size_text, "600×900 px")
        self.assertTrue(all(x.width and x.height for x in res.candidates))

    def test_IMG02_second_run_uses_the_cache_only(self):
        svc = self.service()
        svc.find_covers(self.book)
        first = svc.network_calls
        self.assertGreater(first, 0)
        again = self.service()           # new service, same cache dir
        res = again.find_covers(self.book)
        self.assertEqual(again.network_calls, 0)
        self.assertEqual(len(res.candidates), 4)

    def test_IMG02_cached_404_is_not_requested_again(self):
        routes = self.routes_with({"covers.openlibrary.org/b/isbn/": (404, b"")})
        svc = self.service(routes)
        svc.find_covers(self.book)
        svc2 = self.service(routes)
        svc2.find_covers(self.book)
        self.assertEqual(svc2.network_calls, 0)

    def test_IMG03_audiobook_searches_title_first_and_flags_isbn_art(self):
        audio = c.Book(title="Hyperion", authors=["Dan Simmons"], isbn="9780399178610", format="audio")
        res = self.service().search(audio)
        self.assertNotIn("/isbn/", res.candidates[0].url)
        isbn = [x for x in res.candidates if "/isbn/" in x.url][0]
        self.assertEqual(isbn.note, "may be audiobook art")
        self.assertIs(res.candidates[-1].note != "", True)

    def test_IMG01_no_isbn_falls_back_to_title_and_author(self):
        b = c.Book(title="Secret History", authors=["Brandon Sanderson"])
        svc = self.service()
        svc.find_covers(b)
        searches = [p for (u, p) in self.http.calls if "search.json" in u]
        self.assertEqual(searches[0]["title"], "Secret History")
        self.assertEqual(searches[0]["author"], "Brandon Sanderson")
        self.assertFalse(any("/isbn/" in u for (u, _) in self.http.calls))

    def test_IMG10_network_down_is_reported_not_raised(self):
        down = covers.CoverError("ConnectionError: offline")
        res = self.service({"openlibrary.org": down, "googleapis.com": down}).find_covers(self.book)
        self.assertEqual(res.candidates, [])
        self.assertTrue(res.errors)

    def test_IMG10_one_source_failing_still_returns_the_other(self):
        routes = self.routes_with({"googleapis.com": (503, b"")})
        res = self.service(routes).find_covers(self.book)
        self.assertTrue(res.candidates)
        self.assertTrue(any("Google Books" in e for e in res.errors))

    def test_IMG10_placeholder_and_corrupt_images_are_dropped(self):
        routes = self.routes_with({"covers.openlibrary.org/b/isbn/": (200, png_bytes(1, 1)),
                                   "covers.openlibrary.org/b/id/111": (200, b"not an image")})
        res = self.service(routes).find_covers(self.book)
        for cand in res.candidates:
            self.assertGreater(min(cand.width, cand.height), covers.MIN_IMAGE_SIDE)
        self.assertEqual(len(res.candidates), 2)

    def test_IMG10_malformed_search_json_is_survivable(self):
        routes = self.routes_with({"search.json": (200, b"<html>oops</html>")})
        res = self.service(routes).find_covers(self.book)
        self.assertTrue(res.candidates)
        self.assertTrue(any("Open Library" in e for e in res.errors))

    def test_IMG01_google_api_key_is_sent_only_when_provided(self):
        svc = self.service(google_api_key="K")
        svc.search(self.book)
        g = [p for (u, p) in self.http.calls if "googleapis" in u]
        self.assertTrue(all(p.get("key") == "K" for p in g))
        svc = self.service()
        svc.search(self.book)
        self.assertTrue(all("key" not in p for (u, p) in self.http.calls if "googleapis" in u))

    def test_IMG07_custom_image_upload(self):
        p = Path(tempfile.mkdtemp()) / "mine.png"
        Image.new("RGB", (300, 400), (1, 2, 3)).save(p)
        self.assertEqual(covers.load_local_image(p).size, (300, 400))

    def test_IMG07_bad_custom_image_gives_clear_error(self):
        p = Path(tempfile.mkdtemp()) / "bad.png"
        p.write_bytes(b"nope")
        with self.assertRaises(covers.CoverError):
            covers.load_local_image(p)
        with self.assertRaises(covers.CoverError):
            covers.load_local_image(p.parent / "missing.png")

    def test_IMG04_squarish_candidates_are_identified(self):
        cand = covers.CoverCandidate("x", "u", "l", width=500, height=500)
        self.assertTrue(cand.is_squarish)
        self.assertFalse(covers.CoverCandidate("x", "u", "l", width=400, height=600).is_squarish)


class TestEndToEnd(unittest.TestCase):
    def test_real_export_to_pdf(self):
        s = S.Settings()
        dated, undated = c.filter_books(c.parse_storygraph(REAL_CSV), year=2026)
        books = c.sort_books(dated)
        nets = [net.build_net(b, fake_cover(b.title), s) for b in books]
        out = Path(tempfile.mkdtemp()) / "e2e.pdf"
        pdfexport.export_pdf(nets, s, out)
        with pdfplumber.open(out) as pdf:
            self.assertEqual(len(pdf.pages), 2)            # 28 per page
            self.assertEqual(len(pdf.pages[0].images), 28)
            self.assertEqual(len(pdf.pages[1].images), 7)


if __name__ == "__main__":
    unittest.main()

"""EXP-10 SVG output, TP-01..TP-06 test print page."""
import base64
import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import pdfplumber
from PIL import Image

from minibook import layout, net, settings as S, spine, svgexport, testprint, csvimport as c

NS = {"s": "http://www.w3.org/2000/svg", "x": "http://www.w3.org/1999/xlink"}
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def nets(settings, titles):
    out = []
    for i, t in enumerate(titles):
        b = c.Book(t, ["A B"])
        out.append(net.build_net(b, Image.new("RGB", (600, 900), (30 + i * 10 % 200, 90, 60)), settings))
    return out


class TestSvg(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_EXP10_one_page_is_one_svg_at_real_size_with_the_pictures_inside(self):
        st = S.Settings()
        ns = nets(st, ["One", "Two", "Three"])
        paths = svgexport.export_svg(ns, st, self.tmp / "out.svg")
        self.assertEqual([p.name for p in paths], ["out.svg"])
        root = ET.parse(paths[0]).getroot()
        pw, ph = st.page_mm
        self.assertEqual((root.get("width"), root.get("height")), (f"{pw:g}mm", f"{ph:g}mm"))
        self.assertEqual(root.get("viewBox"), f"0 0 {pw:g} {ph:g}")
        images = root.findall(".//s:image", NS)
        self.assertEqual(len(images), 3)
        grid = layout.make_grid(pw, ph, st.net_width_mm, st.height_mm, st.gutter_mm, st.margin_mm)
        cell = grid.cell(1)
        self.assertAlmostEqual(float(images[1].get("x")), cell.x_mm, places=2)
        self.assertAlmostEqual(float(images[1].get("width")), cell.w_mm, places=2)
        data = images[0].get(XLINK_HREF)
        self.assertTrue(data.startswith("data:image/jpeg;base64,"))
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[1]))).size, ns[0].image.size)

    def test_EXP10_a_600_dpi_sheet_stays_small_enough_to_open(self):
        st = S.Settings(dpi=600)
        ns = nets(st, [f"B{i}" for i in range(28)])
        self.assertEqual(ns[0].image.width, round(st.net_width_mm / 25.4 * 600))
        path = svgexport.export_svg(ns, st, self.tmp / "big.svg")[0]
        self.assertLess(path.stat().st_size, 28 * 400_000)            # the PNG version was 800 KB per book
        root = ET.parse(path).getroot()
        im = root.findall(".//s:image", NS)[0]
        pic = Image.open(io.BytesIO(base64.b64decode(im.get(XLINK_HREF).split(",", 1)[1])))
        self.assertLessEqual(pic.width, round(float(im.get("width")) / 25.4 * svgexport.SVG_MAX_DPI))
        self.assertAlmostEqual(pic.width / pic.height, ns[0].image.width / ns[0].image.height, places=2)

    def test_EXP10_a_real_looking_cover_is_much_smaller_than_png(self):
        import random
        random.seed(1)
        st = S.Settings(dpi=600)
        noisy = Image.effect_noise((600, 900), 60).convert("RGB")
        n = net.build_net(c.Book("N", ["A"]), noisy, st)
        buf = io.BytesIO()
        n.image.save(buf, "PNG")
        data = svgexport._image_data(n.image, st.net_width_mm)
        self.assertLess(len(data), len(buf.getvalue()) / 3)

    def test_EXP10_cut_and_fold_marks_are_vector_lines_matching_the_pdf_marks(self):
        st = S.Settings(fold_marks=True)
        paths = svgexport.export_svg(nets(st, ["One"]), st, self.tmp / "a.svg")
        root = ET.parse(paths[0]).getroot()
        cut = root.find(".//s:g[@id='cut-marks']", NS)
        fold = root.find(".//s:g[@id='fold-marks']", NS)
        self.assertEqual(len(cut), 8)
        self.assertEqual(len(fold), 4)
        grid = layout.make_grid(*st.page_mm, st.net_width_mm, st.height_mm, st.gutter_mm, st.margin_mm)
        first = layout.cut_marks(grid.cell(0), st.gutter_mm)[0]
        line = cut[0]
        self.assertEqual([round(float(line.get(k)), 3) for k in ("x1", "y1", "x2", "y2")], [round(v, 3) for v in first])

    def test_EXP10_fold_marks_can_be_left_out(self):
        st = S.Settings(fold_marks=False)
        root = ET.parse(svgexport.export_svg(nets(st, ["One"]), st, self.tmp / "b.svg")[0]).getroot()
        self.assertIsNone(root.find(".//s:g[@id='fold-marks']", NS))

    def test_EXP10_several_pages_make_numbered_files(self):
        st = S.Settings()
        grid = layout.make_grid(*st.page_mm, st.net_width_mm, st.height_mm, st.gutter_mm, st.margin_mm)
        n = grid.per_page + 2
        paths = svgexport.export_svg(nets(st, [f"B{i}" for i in range(n)]), st, self.tmp / "set")
        self.assertEqual([p.name for p in paths], ["set_page1.svg", "set_page2.svg"])
        self.assertEqual(len(ET.parse(paths[1]).getroot().findall(".//s:image", NS)), 2)

    def test_EXP10_titles_with_xml_characters_are_escaped(self):
        st = S.Settings()
        ns = nets(st, ['Fire & "Ice" <3'])
        root = ET.parse(svgexport.export_svg(ns, st, self.tmp / "e.svg")[0]).getroot()
        g = root.find(".//s:g[@data-title]", NS)
        self.assertEqual(g.get("data-title"), 'Fire & "Ice" <3')

    def test_EXP10_bad_settings_and_no_books_are_refused(self):
        with self.assertRaises(ValueError):
            svgexport.export_svg([], S.Settings(), self.tmp / "x.svg")
        with self.assertRaises(layout.LayoutError):
            svgexport.export_svg(nets(S.Settings(), ["a"]), S.Settings(margin_mm=0.1), self.tmp / "x.svg")


class TestTestPrint(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def page(self, settings, sample=True, name="t.pdf"):
        b = c.Book("Dune", ["Frank Herbert"])
        n = net.build_net(b, Image.new("RGB", (600, 900), (40, 90, 60)), settings) if sample else None
        info = testprint.export_test_print(settings, n, self.tmp / name)
        pdf = pdfplumber.open(self.tmp / name)
        self.assertEqual(len(pdf.pages), 1)
        return info, pdf.pages[0]

    def test_TP01_spine_samples_use_the_smallest_the_largest_and_two_lines(self):
        st = S.Settings(spine_wrap=False)
        (l1, _i1, a), (l2, _i2, b), (l3, _i3, c3) = testprint.spine_samples(st)
        self.assertEqual((l1, l2, l3), ("Min text size", "Max text size", "Title Wrapped to two lines"))
        self.assertAlmostEqual(a.title_pt, st.spine_min_font_pt, delta=0.3)
        self.assertGreater(b.title_pt, a.title_pt * 1.5)
        self.assertLessEqual(b.title_pt, st.spine_max_font_pt + 0.1)
        self.assertEqual(c3.lines is not None and len(c3.lines), 2)       # forced, even with wrap switched off

    def test_TP01_a_spine_too_thin_for_two_lines_says_so(self):
        st = S.Settings(thickness_mm=3.0)
        info, _p = self.page(st)
        self.assertTrue(any("too thin" in n for n in info.notes))

    def test_TP02_the_page_has_three_outlined_books_with_spine_lines_and_the_labelled_spines_as_images(self):
        info, page = self.page(S.Settings())
        self.assertEqual(info.books_in_row, 3)
        rects = [r for r in page.rects if abs(r["height"] - S.Settings().height_mm / 25.4 * 72) < 0.5]
        self.assertEqual(len(rects), 3)
        self.assertEqual(len(page.images), 4)                        # three spines and the full wrap
        spine_lines = [l for l in page.lines if abs(l["x0"] - l["x1"]) < 0.01
                       and abs(abs(l["y1"] - l["y0"]) - S.Settings().height_mm / 25.4 * 72) < 0.5]
        self.assertEqual(len(spine_lines), 6)                        # two spine edges per book

    def test_TP03_the_ruler_is_true_to_size_in_inches(self):
        _i, page = self.page(S.Settings(unit="in"))
        words = {w["text"]: w for w in page.extract_words()}
        centre = lambda w: (w["x0"] + w["x1"]) / 2
        self.assertAlmostEqual(centre(words["1"]) - centre(words["0"]), 72.0, delta=0.6)
        self.assertAlmostEqual(centre(words["7"]) - centre(words["0"]), 7 * 72.0, delta=0.6)
        self.assertIn("inches", words)

    def test_TP03_the_ruler_follows_millimeters_when_that_is_the_unit(self):
        info, page = self.page(S.Settings(unit="mm"))
        self.assertEqual(info.ruler_unit, "mm")
        words = {w["text"]: w for w in page.extract_words()}
        centre = lambda w: (w["x0"] + w["x1"]) / 2
        self.assertAlmostEqual(centre(words["10"]) - centre(words["0"]), 10 / 25.4 * 72, delta=0.5)
        self.assertAlmostEqual(centre(words["100"]) - centre(words["0"]), 100 / 25.4 * 72, delta=0.5)

    def test_TP04_the_ruler_sits_above_the_books(self):
        _i, page = self.page(S.Settings())
        ruler_y = min(w["top"] for w in page.extract_words() if w["text"] == "0")
        books_top = min(r["top"] for r in page.rects)
        self.assertLess(ruler_y, books_top)

    def test_TP05_the_first_book_is_shown_as_a_full_wrap_under_the_first_row(self):
        info, page = self.page(S.Settings())
        self.assertTrue(info.sample_shown)
        row_bottom = max(r["bottom"] for r in page.rects)
        wrap = max(page.images, key=lambda im: im["width"])
        self.assertGreater(wrap["top"], row_bottom - 0.5)
        self.assertAlmostEqual(wrap["width"], S.Settings().net_width_mm / 25.4 * 72, delta=0.5)
        self.assertTrue(any("Dune" in w["text"] for w in page.extract_words()))

    def test_TP05_without_a_ticked_book_the_page_still_prints_and_says_why(self):
        info, page = self.page(S.Settings(), sample=False)
        self.assertFalse(info.sample_shown)
        self.assertTrue(any("No book is ticked" in n for n in info.notes))
        self.assertEqual(len(page.images), 3)
        self.assertIn("ticked", page.extract_text())

    def test_TP06_there_is_no_calibration_square(self):
        _i, page = self.page(S.Settings())
        square = [r for r in page.rects if abs(r["width"] - 72) < 1 and abs(r["height"] - 72) < 1]
        self.assertEqual(square, [])

    def test_TP06_settings_are_written_on_the_page_and_cut_marks_are_drawn(self):
        _i, page = self.page(S.Settings(dpi=300))
        text = page.extract_text()
        self.assertIn("300 dpi", text)
        self.assertIn("100%", text)
        self.assertGreaterEqual(len(page.lines), 3 * 8)

    def test_TP07_a4_and_a_narrow_board_work_and_a_page_with_no_room_is_refused(self):
        info, page = self.page(S.Settings(paper="a4"))
        self.assertAlmostEqual(page.width, 595.3, delta=0.6)
        with self.assertRaises(layout.LayoutError):
            testprint.export_test_print(S.Settings(height_mm=255.0, width_mm=20.0, thickness_mm=5.0), None, self.tmp / "no.pdf")


if __name__ == "__main__":
    unittest.main()

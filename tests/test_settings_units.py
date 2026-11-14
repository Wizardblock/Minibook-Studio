"""DIM-01..05, SET-01..03, EXP-02/04/06 (settings side)."""
import json
import tempfile
import unittest
from pathlib import Path

from minibook import settings as S, units


class TestUnits(unittest.TestCase):
    def test_DIM03_unit_round_trip(self):
        self.assertAlmostEqual(units.to_mm(1, "in"), 25.4)
        self.assertAlmostEqual(units.from_mm(25.4, "in"), 1.0)
        self.assertEqual(units.to_mm(12.5, "mm"), 12.5)
        with self.assertRaises(ValueError):
            units.to_mm(1, "cm")

    def test_DIM01_aspect_parsing(self):
        self.assertAlmostEqual(units.parse_aspect("2:3"), 2 / 3)
        self.assertAlmostEqual(units.parse_aspect("2/3"), 2 / 3)
        self.assertAlmostEqual(units.parse_aspect("0.667"), 0.667)
        self.assertAlmostEqual(units.parse_aspect(0.5), 0.5)
        for bad in ("", "abc", "0", "50"):
            with self.assertRaises(ValueError):
                units.parse_aspect(bad)

    def test_DIM04_scale_calculator_1_to_12(self):
        w, h, t = units.scale_dimensions(6, 9, 3, 12)
        self.assertEqual((w, h, t), (0.5, 0.75, 0.25))

    def test_DIM05_default_dpi_is_300(self):
        self.assertEqual(S.Settings().dpi, 300)

    def test_px_conversion_at_300dpi(self):
        self.assertEqual(units.mm_to_px(25.4, 300), 300)
        self.assertEqual(units.mm_to_px(units.in_to_mm(0.25), 300), 75)


class TestSettingsDimensions(unittest.TestCase):
    def test_DIM02_defaults_are_1_25_by_0_75_with_quarter_inch_spine(self):
        s = S.Settings()
        self.assertAlmostEqual(units.mm_to_in(s.thickness_mm), 0.25)
        self.assertAlmostEqual(units.mm_to_in(s.height_mm), 1.25)
        self.assertAlmostEqual(units.mm_to_in(s.board_width_mm), 0.75)
        self.assertEqual(s.validate(), [])

    def test_DIM01_height_plus_width_mode(self):
        s = S.Settings(size_mode="width", height_mm=40, width_mm=25)
        self.assertEqual(s.board_width_mm, 25)

    def test_DIM01_height_plus_aspect_mode(self):
        s = S.Settings(size_mode="aspect", height_mm=60, aspect=2 / 3)
        self.assertAlmostEqual(s.board_width_mm, 40)
        self.assertAlmostEqual(s.net_width_mm, 80 + s.thickness_mm)

    def test_EXP02_gutter_below_minimum_is_rejected(self):
        self.assertTrue(any("gutter" in p for p in S.Settings(gutter_mm=1.0).validate()))

    def test_EXP06_margin_too_small_for_marks_is_rejected(self):
        s = S.Settings(gutter_mm=10, margin_mm=1.0)   # marks need 0.5 + 3.0 mm
        self.assertTrue(any("margin" in p for p in s.validate()))
        self.assertEqual(S.Settings(gutter_mm=10, margin_mm=4.0).validate(), [])

    def test_oversized_book_is_rejected(self):
        self.assertTrue(any("fit" in p for p in S.Settings(height_mm=400).validate()))

    def test_EXP04_there_is_no_print_mode_any_more_only_a_margin(self):
        self.assertFalse(hasattr(S.Settings(), "mode"))
        self.assertEqual(S.Settings(margin_mm=3.0).validate(), [])      # plain paper may use a small margin

    def test_EXP04_an_old_settings_file_with_a_mode_still_loads(self):
        import json
        import tempfile
        p = Path(tempfile.mkdtemp()) / "s.json"
        p.write_text(json.dumps({"mode": "sticker", "margin_mm": 7.0}))
        loaded = S.load_settings(p)
        self.assertEqual(loaded.margin_mm, 7.0)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "settings.json"

    def test_SET01_round_trip(self):
        s = S.Settings(unit="mm", back_style="complement", gutter_mm=6.0, margin_mm=7.0,
                       spine_hide_author=True, dpi=600)
        S.save_settings(s, self.path)
        loaded = S.load_settings(self.path)
        self.assertEqual(loaded, s)

    def test_SET02_missing_file_gives_defaults(self):
        self.assertEqual(S.load_settings(self.tmp / "nope.json"), S.Settings())

    def test_SET02_corrupt_file_gives_defaults(self):
        self.path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(S.load_settings(self.path), S.Settings())

    def test_SET02_wrong_shape_gives_defaults(self):
        self.path.write_text("[1,2,3]", encoding="utf-8")
        self.assertEqual(S.load_settings(self.path), S.Settings())

    def test_SET02_bad_field_keeps_default_for_that_field_only(self):
        self.path.write_text(json.dumps({"dpi": "huge", "back_style": "complement", "future_field": 1}))
        s = S.load_settings(self.path)
        self.assertEqual(s.dpi, 300)
        self.assertEqual(s.back_style, "complement")

    def test_SET02_unprintable_combination_falls_back_to_defaults(self):
        self.path.write_text(json.dumps({"height_mm": -5}))
        self.assertEqual(S.load_settings(self.path), S.Settings())

    def test_SET02_boolean_is_not_accepted_as_number(self):
        self.path.write_text(json.dumps({"dpi": True}))
        self.assertEqual(S.load_settings(self.path).dpi, 300)

    def test_SET03_book_prefs_round_trip(self):
        p = self.tmp / "prefs.json"
        prefs = {"abc": S.BookPrefs(cover_url="https://x/y.jpg", zoom=1.4, pan_x=0.2, pan_y=0.9),
                 "def": S.BookPrefs(custom_path="/tmp/me.png")}
        S.save_book_prefs(prefs, p)
        self.assertEqual(S.load_book_prefs(p), prefs)

    def test_SET03_corrupt_prefs_do_not_crash(self):
        p = self.tmp / "prefs.json"
        p.write_text("garbage")
        self.assertEqual(S.load_book_prefs(p), {})
        p.write_text(json.dumps({"a": {"zoom": "big"}, "b": 5}))
        loaded = S.load_book_prefs(p)
        self.assertEqual(loaded["a"].zoom, 1.0)
        self.assertNotIn("b", loaded)


if __name__ == "__main__":
    unittest.main()

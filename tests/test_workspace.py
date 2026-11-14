"""WS-01..WS-06: save and open the whole workspace."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from minibook import controller as ctlmod, covers, csvimport as c, settings as S, workspace
from tests.helpers import FakeHttp, json_bytes, png_bytes

CSV = (b"Title,Authors,ISBN/UID,Format,Read Status,Last Date Read,Star Rating\n"
       b"Dune,Frank Herbert,9780441013593,paperback,read,2025/03/02,4.5\n"
       b"Emma,Jane Austen,,hardcover,read,2025/05/01,3\n"
       b"Old Book,Some One,,paperback,read,2023/01/01,\n")


def routes():
    return {"covers.openlibrary.org/b/isbn/": (200, png_bytes(600, 900, (20, 120, 40))),
            "openlibrary.org": (200, json_bytes({"docs": []})),
            "googleapis.com": (200, json_bytes({"items": []})),
            "images-na.ssl-images-amazon.com": (404, b"")}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ctl = self.make("a")

    def make(self, name, online=True):
        d = self.tmp / name
        svc = covers.CoverService(FakeHttp(routes() if online else {}), d / "cache") if online else None
        return ctlmod.AppController(S.Settings(google_api_key="SECRETKEY", output_dir="/home/me/private"), {}, svc,
                                    settings_path=d / "s.json", prefs_path=d / "p.json", custom_dir=d / "cu",
                                    edits_path=d / "e.json")

    def build(self):
        ctl = self.ctl
        ctl.load_csv(CSV, "my export.csv")
        ctl.apply_filter(2025, {"read"})
        by = {b.title: b for b in ctl.all_books}
        ctl.add_manual("Hand Book", "Me Myself", "", "2024-06", 4)
        ctl.ensure_cover(by["Dune"])
        ctl.set_spine_color(by["Dune"], (200, 10, 10))
        ctl.set_crop(by["Dune"], zoom=1.5, pan_x=0.3)
        ctl.set_custom_image(by["Emma"], png_bytes(321, 654, (10, 90, 200)))
        by["Emma"].selected = False
        return by


class TestRoundTrip(Base):
    def test_WS01_books_filter_ticks_and_hand_added_books_come_back(self):
        by = self.build()
        data = self.ctl.save_workspace()
        other = self.make("b")
        info = other.open_workspace(data)
        self.assertEqual(info["books"], 4)
        self.assertEqual(info["by_hand"], 1)
        self.assertEqual({b.title for b in other.all_books}, {"Dune", "Emma", "Old Book"})
        self.assertEqual([b.title for b in other.manual], ["Hand Book"])
        self.assertEqual((other.year, other.statuses, other.csv_name), (2025, {"read"}, "my export.csv"))
        self.assertEqual([b.title for b in other.dated], [b.title for b in self.ctl.dated])
        sel = {b.title: b.selected for b in other.visible()}
        self.assertEqual(sel, {b.title: b.selected for b in self.ctl.visible()})
        self.assertFalse(sel["Emma"])
        hand = other.manual[0]
        self.assertEqual((str(hand.read_date), hand.rating, hand.source), ("2024-06", 4.0, "manual"))

    def test_WS02_chosen_covers_crops_and_colors_come_back_without_the_internet(self):
        by = self.build()
        other = self.make("b", online=False)
        other.open_workspace(self.ctl.save_workspace())
        dune = next(b for b in other.all_books if b.title == "Dune")
        p = other.book_prefs(dune)
        self.assertEqual((p.spine_color, p.zoom, p.pan_x), ("#c80a0a", 1.5, 0.3))
        st = other.state(dune)
        self.assertTrue(st.searched and st.image is not None)
        self.assertEqual(st.image.size, self.ctl.state(by["Dune"]).image.size)
        self.assertEqual(other.net_for(dune).color, (200, 10, 10))

    def test_WS03_uploaded_images_come_back_and_stay_available_when_not_in_use(self):
        by = self.build()
        emma = by["Emma"]
        st = self.ctl.ensure_cover(emma)
        self.assertTrue(st.custom)
        dune_prefs = self.ctl.book_prefs(by["Dune"])
        self.ctl.set_custom_image(by["Dune"], png_bytes(300, 450))
        self.ctl.choose_candidate(by["Dune"], self.ctl.state(by["Dune"]).candidates[0]) \
            if self.ctl.state(by["Dune"]).candidates else None
        other = self.make("b")
        other.open_workspace(self.ctl.save_workspace())
        e2 = next(b for b in other.all_books if b.title == "Emma")
        self.assertTrue(other.state(e2).custom)
        self.assertEqual(other.state(e2).image.size, (321, 654))
        self.assertEqual(other.custom_candidate(e2).size_text, "321×654 px")
        self.assertTrue(Path(other.book_prefs(e2).custom_path).exists())
        self.assertIn(str(other.custom_dir), other.book_prefs(e2).custom_path)     # a copy in this computer's folder

    def test_WS04_the_google_key_and_save_folder_are_never_in_the_file(self):
        self.build()
        data = self.ctl.save_workspace()
        blob = b"".join(zipfile.ZipFile(io.BytesIO(data)).read(n) for n in zipfile.ZipFile(io.BytesIO(data)).namelist()
                        if n.endswith(".json"))
        self.assertNotIn(b"SECRETKEY", blob)
        self.assertNotIn(b"/home/me/private", blob)
        other = self.make("b")
        other.update_settings(google_api_key="MINE", output_dir="/mine")
        other.open_workspace(data)
        self.assertEqual((other.settings.google_api_key, other.settings.output_dir), ("MINE", "/mine"))

    def test_WS05_output_settings_travel_with_the_workspace(self):
        self.build()
        self.ctl.update_settings(gutter_mm=7.0, fold_marks=False)
        other = self.make("b")
        other.open_workspace(self.ctl.save_workspace())
        self.assertEqual((other.settings.gutter_mm, other.settings.fold_marks), (7.0, False))

    def test_WS06_opening_replaces_what_was_there(self):
        self.build()
        data = self.ctl.save_workspace()
        other = self.make("b")
        other.load_csv(b"Title,Authors\nZed,Zoe\n", "z.csv")
        other.add_manual("Gone")
        other.open_workspace(data)
        self.assertNotIn("Zed", [b.title for b in other.visible()])
        self.assertNotIn("Gone", [b.title for b in other.manual])

    def test_WS01_an_empty_workspace_round_trips(self):
        other = self.make("b")
        info = other.open_workspace(self.ctl.save_workspace())
        self.assertEqual(info["books"], 0)

    def test_WS01_the_pdf_made_from_a_reopened_workspace_matches(self):
        self.build()
        self.ctl.ensure_cover(self.ctl.manual[0])
        a = self.ctl.export(out_path=self.tmp / "a.pdf")[2]
        other = self.make("b", online=False)
        other.open_workspace(self.ctl.save_workspace())
        b = other.export(out_path=self.tmp / "b.pdf")[2]
        self.assertEqual(a, b)

    def test_WS07_the_reopened_workspace_persists_its_choices_for_next_launch(self):
        self.build()
        other = self.make("b")
        other.open_workspace(self.ctl.save_workspace())
        again = ctlmod.AppController(S.Settings(), S.load_book_prefs(self.tmp / "b" / "p.json"), None,
                                     persist=False, custom_dir=self.tmp / "b" / "cu")
        dune = next(b for b in other.all_books if b.title == "Dune")
        self.assertEqual(again.prefs[dune.id].spine_color, "#c80a0a")


class TestBadFiles(Base):
    def refused(self, data):
        other = self.make("b")
        other.load_csv(CSV, "keep.csv")
        before = [b.title for b in other.visible()]
        with self.assertRaises(workspace.WorkspaceError) as cm:
            other.open_workspace(data)
        self.assertEqual([b.title for b in other.visible()], before)        # nothing changed
        self.assertEqual(other.csv_name, "keep.csv")
        return str(cm.exception)

    def zipped(self, meta=None, extra=None, raw=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("workspace.json", raw if raw is not None else json.dumps(meta))
            for k, v in (extra or {}).items():
                z.writestr(k, v)
        return buf.getvalue()

    def test_WS08_not_a_zip_or_not_ours(self):
        self.assertIn("not a MiniBook", self.refused(b"hello"))
        self.assertIn("not a MiniBook", self.refused(self.zipped(raw="{not json")))
        self.assertIn("not a MiniBook", self.refused(self.zipped({"format": "other"})))
        self.assertIn("not a MiniBook", self.refused(self.zipped(raw=json.dumps([1, 2]))))

    def test_WS08_a_newer_version_is_refused_with_a_clear_message(self):
        self.assertIn("newer version", self.refused(self.zipped({"format": workspace.FORMAT, "version": 99, "books": []})))

    def test_WS08_a_broken_book_or_image_refuses_the_whole_file(self):
        base = {"format": workspace.FORMAT, "version": 1}
        self.assertIn("without a title", self.refused(self.zipped({**base, "books": [{"title": ""}]})))
        self.assertIn("no list of books", self.refused(self.zipped({**base, "books": "x"})))
        bad = self.zipped({**base, "books": [{"title": "A"}], "covers": {"0": "covers/0.jpg"}},
                          {"covers/0.jpg": b"not an image"})
        self.assertIn("could not be read", self.refused(bad))
        missing = self.zipped({**base, "books": [{"title": "A"}], "covers": {"0": "covers/0.jpg"}})
        self.assertIn("missing", self.refused(missing))

    def test_WS08_an_oversized_part_is_refused(self):
        base = {"format": workspace.FORMAT, "version": 1, "books": [{"title": "A"}], "covers": {"0": "covers/0.jpg"}}
        old = workspace.MAX_IMAGE_BYTES
        workspace.MAX_IMAGE_BYTES = 10
        try:
            self.assertIn("too large", self.refused(self.zipped(base, {"covers/0.jpg": b"x" * 50})))
        finally:
            workspace.MAX_IMAGE_BYTES = old

    def test_WS08_bad_prefs_do_not_stop_a_good_file(self):
        base = {"format": workspace.FORMAT, "version": 1, "books": [{"title": "A", "group": "csv"}],
                "prefs": {"0": {"zoom": "bad", "unknown": 1}, "7": {}, "x": 1}}
        other = self.make("b")
        other.open_workspace(self.zipped(base))
        self.assertEqual([b.title for b in other.all_books], ["A"])

    def test_WS08_names_inside_the_file_cannot_reach_outside_it(self):
        base = {"format": workspace.FORMAT, "version": 1, "books": [{"title": "A"}],
                "covers": {"0": "../../etc/passwd"}}
        self.assertIn("missing", self.refused(self.zipped(base)))


if __name__ == "__main__":
    unittest.main()

"""DATA-11 Goodreads import, DATA-12 typing in a read date and star rating."""
import json
import tempfile
import unittest
from pathlib import Path

from minibook import controller as ctlmod, csvimport as c, preview as pv, settings as S

HEADER = ("Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,Publisher,Binding,"
          "Number of Pages,Year Published,Original Publication Year,Date Read,Date Added,Bookshelves,"
          "Bookshelves with positions,Exclusive Shelf,My Review,Spoiler,Private Notes,Read Count,Owned Copies\n")
HITCH = ('''11,"The Hitchhiker's Guide to the Galaxy (The Hitchhiker's Guide to the Galaxy, #1)",Douglas Adams,'''
         '''"Adams, Douglas",,"=""""","=""""",3.75,Del Rey Books,Mass Market Paperback,216,2005,1979,2026/10/30,'''
         '''2026/10/30,,,read,,,,1,0\n''')
MARTIAN = ('''18007564,The Martian,Andy Weir,"Weir, Andy",,"=""0804139024""","=""9780804139021""",4.5,Crown,'''
           '''Hardcover,369,2014,2011,2025/02/11,2026/10/30,,,read,"Great<br/>book",,,1,0\n''')
EXTRA = (
    '''1,Unrated Thing,Some Author,"Author, Some","Helper One, Helper Two","=""""","=""""",0,X,Audible Audio,1,2020,2020,,2020/01/01,,,to-read,,,,0,0\n'''
    '''2,Ten Digit Only,Other Writer,"Writer, Other",,"=""076532637X""","=""""",5,X,Kindle Edition,1,2020,2020,2024/03,2020/01/01,,,read,,,,1,0\n'''
    '''3,Dune (Dune Chronicles #1),Frank Herbert,"Herbert, Frank",,"=""""","=""""",4,X,Hardcover,1,1965,1965,2023/07/04,2020/01/01,,,read,,,,1,0\n''')
CSV = (HEADER + HITCH + MARTIAN + EXTRA).encode("utf-8")


class TestGoodreadsImport(unittest.TestCase):
    def books(self):
        return {b.title: b for b in c.parse_library_csv(CSV)}

    def test_DATA11_the_columns_tell_goodreads_from_storygraph(self):
        self.assertEqual(len(c.parse_library_csv(CSV)), 5)
        sg = b"Title,Authors,ISBN/UID,Format,Read Status,Last Date Read,Dates Read,Star Rating,Review\nA,B,,,read,2024/01/02,,4,\n"
        self.assertEqual([b.title for b in c.parse_library_csv(sg)], ["A"])

    def test_DATA11_something_else_gets_a_message_naming_both_services(self):
        with self.assertRaises(c.CsvFormatError) as cm:
            c.parse_library_csv(b"a,b\n1,2\n")
        self.assertIn("Goodreads", str(cm.exception))
        self.assertIn("StoryGraph", str(cm.exception))

    def test_DATA11_series_text_is_dropped_from_the_title(self):
        t = self.books()
        self.assertIn("The Hitchhiker's Guide to the Galaxy", t)
        self.assertIn("Dune", t)
        self.assertEqual(c.clean_goodreads_title("Title (Not A Series)"), "Title (Not A Series)")
        self.assertEqual(c.clean_goodreads_title("(#1)"), "(#1)")                # never leaves an empty title

    def test_DATA11_isbn_comes_out_of_the_spreadsheet_quoting(self):
        t = self.books()
        self.assertEqual(t["The Martian"].isbn, "9780804139021")
        self.assertIsNone(t["The Hitchhiker's Guide to the Galaxy"].isbn)
        self.assertEqual(t["Ten Digit Only"].isbn, c.isbn10_to_13("076532637X"))      # falls back to the ISBN-10

    def test_DATA11_dates_and_ratings(self):
        t = self.books()
        self.assertEqual(str(t["The Martian"].read_date), "2025-02-11")
        self.assertEqual(t["The Martian"].rating, 4.5)
        self.assertEqual(t["The Hitchhiker's Guide to the Galaxy"].rating, 3.75)
        self.assertEqual(str(t["Ten Digit Only"].read_date), "2024-03")
        self.assertIsNone(t["Unrated Thing"].read_date)
        self.assertIsNone(t["Unrated Thing"].rating)             # 0 means "not rated"

    def test_DATA11_status_format_authors_and_review(self):
        t = self.books()
        self.assertEqual(t["The Martian"].status, "read")
        self.assertEqual(t["Unrated Thing"].status, "to-read")
        self.assertEqual(t["The Martian"].format, "hardcover")
        self.assertEqual(t["Unrated Thing"].format, "audio")
        self.assertEqual(t["Ten Digit Only"].format, "digital")
        self.assertEqual(t["The Hitchhiker's Guide to the Galaxy"].format, "paperback")
        self.assertEqual(t["Unrated Thing"].authors, ["Some Author", "Helper One", "Helper Two"])
        self.assertEqual(t["The Martian"].review, "Great\nbook")

    def test_DATA11_the_controller_loads_it_and_filters_by_year_like_any_export(self):
        ctl = ctlmod.AppController(S.Settings(), {}, None, persist=False)
        info = ctl.load_csv(CSV, "goodreads_library_export.csv")
        self.assertEqual(info["years"], [2026, 2025, 2024, 2023])
        self.assertEqual({b.title for b in ctl.dated}, {"The Hitchhiker's Guide to the Galaxy"})
        self.assertEqual([b.title for b in ctl.undated if b.status == "read"], [])

    def test_DATA11_bom_and_text_input_work(self):
        self.assertEqual(len(c.parse_library_csv(b"\xef\xbb\xbf" + CSV)), 5)
        self.assertEqual(len(c.parse_library_csv(CSV.decode())), 5)


class TestUserDateAndRating(unittest.TestCase):
    def test_DATA12_dates_in_three_precisions(self):
        self.assertEqual(str(c.parse_user_date("2024")), "2024")
        self.assertEqual(str(c.parse_user_date("2024-5")), "2024-05")
        self.assertEqual(str(c.parse_user_date(" 2024/05/17 ")), "2024-05-17")
        self.assertEqual(str(c.parse_user_date("2024.05.07")), "2024-05-07")
        self.assertIsNone(c.parse_user_date("  "))

    def test_DATA12_bad_dates_are_refused_with_a_reason(self):
        for bad in ("May 2024", "24", "2024-13", "2024-02-30", "1800", "2024-05-17-1", "2024-00"):
            with self.assertRaises(ValueError, msg=bad):
                c.parse_user_date(bad)
        self.assertEqual(str(c.parse_user_date("2024-02-29")), "2024-02-29")        # leap day
        with self.assertRaises(ValueError):
            c.parse_user_date("2023-02-29")

    def test_DATA12_ratings_round_to_quarter_stars(self):
        self.assertEqual(c.parse_user_rating(4), 4.0)
        self.assertEqual(c.parse_user_rating("3.7"), 3.75)
        self.assertEqual(c.parse_user_rating(0.5), 0.5)
        for blank in (None, "", "  ", 0, "0"):
            self.assertIsNone(c.parse_user_rating(blank))

    def test_DATA12_bad_ratings_are_refused(self):
        for bad in (5.5, -1, "five", 6):
            with self.assertRaises(ValueError, msg=str(bad)):
                c.parse_user_rating(bad)

    def test_DATA12_a_book_added_by_hand_can_carry_both(self):
        b = c.manual_book("Dune", "Frank Herbert", read_date="2024-05", rating=4.25)
        self.assertEqual((str(b.read_date), b.rating, b.year), ("2024-05", 4.25, 2024))
        self.assertIsNone(c.manual_book("Dune").read_date)

    def test_DATA12_a_bad_edit_changes_nothing(self):
        b = c.manual_book("Dune", "F", read_date="2024", rating=3)
        with self.assertRaises(ValueError):
            c.apply_edit(b, "Dune 2", "F", "", read_date="2024", rating=9)
        with self.assertRaises(ValueError):
            c.apply_edit(b, "Dune 2", "F", "", read_date="nonsense", rating=4)
        self.assertEqual((b.title, b.rating, str(b.read_date)), ("Dune", 3, "2024"))

    def test_DATA12_leaving_the_fields_out_keeps_them_and_blank_clears_them(self):
        b = c.manual_book("Dune", "F", read_date="2024", rating=3)
        c.apply_edit(b, "Dune", "F", "")
        self.assertEqual((str(b.read_date), b.rating), ("2024", 3))
        c.apply_edit(b, "Dune", "F", "", read_date="", rating=None)
        self.assertEqual((b.read_date, b.rating), (None, None))


class TestControllerEditing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ctl = self.make()
        self.ctl.load_csv(CSV, "g.csv")
        self.ctl.apply_filter(None, {"read"})

    def make(self):
        return ctlmod.AppController(S.Settings(), {}, None, settings_path=self.tmp / "s.json",
                                    prefs_path=self.tmp / "p.json", custom_dir=self.tmp / "c",
                                    edits_path=self.tmp / "e.json")

    def book(self, title):
        return next(b for b in self.ctl.all_books if b.title == title)

    def test_DATA12_a_date_and_rating_added_to_an_undated_book_are_remembered_across_imports(self):
        b = self.book("Unrated Thing")
        self.ctl.edit_book(b, b.title, b.author, "", read_date="2022-06-01", rating=4)
        again = self.make()
        again.load_csv(CSV, "g.csv")
        got = next(x for x in again.all_books if x.title == "Unrated Thing")
        self.assertEqual((str(got.read_date), got.rating), ("2022-06-01", 4.0))

    def test_DATA12_clearing_a_date_is_remembered_too(self):
        b = self.book("The Martian")
        self.ctl.edit_book(b, b.title, b.author, b.isbn or "", read_date="", rating=None)
        again = self.make()
        again.load_csv(CSV, "g.csv")
        got = next(x for x in again.all_books if x.title == "The Martian")
        self.assertEqual((got.read_date, got.rating), (None, None))

    def test_DATA12_old_saved_edits_without_these_fields_still_load(self):
        (self.tmp / "e.json").write_text(json.dumps({self.book("Dune").source_id: {
            "title": "Dune Renamed", "author": "Frank Herbert", "isbn": ""}}))
        again = self.make()
        again.load_csv(CSV, "g.csv")
        got = next(x for x in again.all_books if x.title == "Dune Renamed")
        self.assertEqual(str(got.read_date), "2023-07-04")
        self.assertEqual(got.rating, 4.0)

    def test_DATA12_date_or_rating_only_does_not_send_the_book_to_cover_search_again(self):
        b = self.book("The Martian")
        self.ctl.cover_state[b.id] = ctlmod.CoverState(searched=True)
        self.ctl.edit_book(b, b.title, b.author, b.isbn, read_date="2020", rating=1)
        self.assertNotIn(b.id, self.ctl.pending)
        self.assertTrue(self.ctl.cover_state[b.id].searched)
        self.ctl.edit_book(b, "The Martian!", b.author, b.isbn, read_date="2020", rating=1)
        self.assertIn(b.id, self.ctl.pending)

    def test_DATA12_a_new_date_moves_the_book_between_the_groups_and_keeps_other_ticks(self):
        ctl = self.ctl
        ctl.apply_filter(2025, {"read"})
        martian, dune = self.book("The Martian"), self.book("Dune")
        self.assertIn(martian, ctl.dated)
        martian.selected = False
        ctl.edit_book(dune, dune.title, dune.author, "", read_date="2025-01-01", rating=4)
        self.assertIn(dune, ctl.dated)                                   # now matches 2025
        self.assertFalse(martian.selected)                               # the user's choice is kept
        ctl.edit_book(martian, martian.title, martian.author, martian.isbn, read_date="2019", rating=4)
        self.assertNotIn(martian, ctl.dated)                             # 2019 is no longer the year shown

    def test_DATA12_added_by_hand_through_the_controller_and_the_preview_notices_changes(self):
        b = self.ctl.add_manual("Hand Made", "Me", "", "2024-02-03", 5)
        self.assertEqual((str(b.read_date), b.rating), ("2024-02-03", 5.0))
        before = pv._book_signature(b)
        self.ctl.edit_book(b, b.title, b.author, "", read_date="2024-02-04", rating=5)
        after = pv._book_signature(b)
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()

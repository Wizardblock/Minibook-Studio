"""DATA-01..09, TST-02 (uses the real StoryGraph export in tests/data)."""
import unittest

from minibook import csvimport as c
from tests.helpers import REAL_CSV


class TestRealExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.books = c.parse_storygraph(REAL_CSV)
        cls.by_title = {}
        for b in cls.books:
            cls.by_title.setdefault(b.title, []).append(b)

    def test_DATA01_parses_every_row(self):
        self.assertEqual(len(self.books), 157)

    def test_DATA01_status_counts_match_the_file(self):
        read = [b for b in self.books if b.status == "read"]
        self.assertEqual(len(read), 82)
        self.assertEqual(len([b for b in self.books if b.status == "to-read"]), 69)

    def test_DATA02_default_filter_is_read_only(self):
        dated, undated = c.filter_books(self.books)
        self.assertTrue(all(b.status == "read" for b in dated + undated))
        self.assertEqual(len(dated) + len(undated), 82)

    def test_DATA02_year_filter(self):
        dated, _ = c.filter_books(self.books, year=2026)
        self.assertEqual(len(dated), 35)
        self.assertTrue(all(b.year == 2026 for b in dated))
        self.assertEqual(c.available_years(self.books), [2026, 2025, 2024])

    def test_DATA02_other_status_selectable(self):
        dated, undated = c.filter_books(self.books, statuses={"currently-reading"})
        self.assertEqual({b.title for b in dated + undated}, {"Soul Music", "Bryony and Roses"})

    def test_DATA03_date_formats(self):
        d = c.parse_read_date
        self.assertEqual(str(d("2026/01/23", "")), "2026-01-23")
        self.assertEqual(str(d("2025/07", "2025/07")), "2025-07")
        self.assertEqual(str(d("2025", "2025")), "2025")
        self.assertIsNone(d("", ""))

    def test_DATA03_falls_back_to_dates_read(self):
        self.assertEqual(str(c.parse_read_date("", "2026/01/05-2026/04/11")), "2026-04-11")

    def test_DATA03_trailing_dash_year_is_recovered(self):
        # "Land's End" has Last Date Read blank and Dates Read "2024-"
        self.assertEqual(self.by_title["Land's End"][0].year, 2024)

    def test_DATA03_garbage_dates_are_ignored(self):
        self.assertIsNone(c.parse_read_date("soon", "n/a"))
        self.assertIsNone(c.parse_read_date("0000/13/45", ""))
        self.assertEqual(str(c.parse_read_date("2026/13/45", "")), "2026")

    def test_DATA04_undated_books_are_kept_and_unchecked(self):
        dated, undated = c.filter_books(self.books, year=2026)
        self.assertEqual(len(undated), 18)
        c.apply_default_selection(dated, undated)
        self.assertTrue(all(b.selected for b in dated))
        self.assertFalse(any(b.selected for b in undated))
        self.assertTrue(all(b.read_date is None for b in undated))

    def test_DATA05_selection_can_be_toggled(self):
        dated, undated = c.filter_books(self.books, year=2026)
        c.apply_default_selection(dated, undated)
        dated[0].selected = False
        self.assertEqual(sum(b.selected for b in dated), len(dated) - 1)

    def test_DATA07_sort_by_author_then_date(self):
        dated, _ = c.filter_books(self.books, year=2026)
        order = [b.title for b in c.sort_books(dated, "author") if b.author == "Orson Scott Card"]
        self.assertEqual(order, ["The Memory of Earth", "The Call of Earth", "The Ships of Earth",
                                 "Earthfall", "Earthborn"])
        authors = [b.authors[0].split()[-1].lower() for b in c.sort_books(dated, "author")]
        self.assertEqual(authors, sorted(authors))

    def test_DATA07_other_sorts(self):
        dated, _ = c.filter_books(self.books, year=2026)
        titles = [b.title.lower() for b in c.sort_books(dated, "title")]
        self.assertEqual(titles, sorted(titles))
        dates = [b.read_date.sort_key() for b in c.sort_books(dated, "date")]
        self.assertEqual(dates, sorted(dates))

    def test_DATA08_trailing_space_trimmed(self):
        self.assertIn("Raising Steam", self.by_title)

    def test_DATA08_multiple_authors_split(self):
        self.assertEqual(self.by_title["The Shepherd's Crown"][0].authors, ["Terry Pratchett", "Rob Wilkins"])

    def test_DATA08_isbn10_converted_to_isbn13(self):
        # Wyrd Sisters has ISBN-10 0552134600
        self.assertEqual(self.by_title["Wyrd Sisters"][0].isbn, "9780552134606")

    def test_DATA08_asin_is_not_an_isbn(self):
        mp = self.by_title["Moving Pictures"][0]
        self.assertIsNone(mp.isbn)
        self.assertEqual(mp.asin, "B00351YF0C")

    def test_DATA08_blank_isbn_and_rating_are_none(self):
        b = self.by_title["Secret History"][0]
        self.assertIsNone(b.isbn)
        self.assertEqual(b.rating, 3.75)
        self.assertIsNone(self.by_title["Oathbringer"][0].rating)

    def test_DATA08_html_stripped_from_reviews(self):
        r = self.by_title["Secret History"][0].review
        self.assertNotIn("<", r)
        self.assertNotIn("&nbsp;", r)
        self.assertTrue(r.startswith("A nice length novella"))

    def test_DATA08_every_isbn_in_real_file_is_valid_13(self):
        for b in self.books:
            if b.isbn:
                self.assertTrue(c.isbn13_valid(b.isbn), b.title)

    def test_DATA09_duplicate_titles_flagged(self):
        dups = c.flag_duplicates([b for b in self.books if b.status in ("read", "")])
        self.assertEqual(dups, ["The Martian"])
        self.assertTrue(all(b.duplicate for b in self.by_title["The Martian"]))
        self.assertFalse(self.by_title["Mort"][0].duplicate)

    def test_book_ids_are_stable_and_distinct(self):
        a, b = self.by_title["The Martian"]
        self.assertNotEqual(a.id, b.id)
        again = c.parse_storygraph(REAL_CSV)
        self.assertEqual([x.id for x in again], [x.id for x in self.books])


class TestParserEdges(unittest.TestCase):
    def test_DATA01_bom_and_quotes(self):
        text = '﻿Title,Authors,ISBN/UID\n"Hello, World","A, B",9780765326355\n'
        b = c.parse_storygraph(text)[0]
        self.assertEqual(b.title, "Hello, World")
        self.assertEqual(b.authors, ["A", "B"])

    def test_DATA01_wrong_file_gives_clear_error(self):
        with self.assertRaises(c.CsvFormatError) as cm:
            c.parse_storygraph("Name,Age\nBob,3\n")
        self.assertIn("StoryGraph", str(cm.exception))

    def test_DATA01_rows_without_title_skipped(self):
        self.assertEqual(c.parse_storygraph("Title,Authors\n,Nobody\nReal,Me\n")[0].title, "Real")

    def test_DATA01_empty_file(self):
        self.assertEqual(c.parse_storygraph("Title,Authors\n"), [])

    def test_DATA06_manual_entry(self):
        b = c.manual_book("  Dune ", "Frank Herbert", "0-441-17271-7")
        self.assertEqual((b.title, b.authors, b.source), ("Dune", ["Frank Herbert"], "manual"))
        self.assertEqual(b.isbn, "9780441172719")

    def test_DATA06_manual_entry_requires_title(self):
        with self.assertRaises(ValueError):
            c.manual_book("   ")

    def test_DATA06_manual_entry_bad_isbn_is_ignored_not_fatal(self):
        self.assertIsNone(c.manual_book("X", "", "123").isbn)


if __name__ == "__main__":
    unittest.main()

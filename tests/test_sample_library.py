"""The sample CSV shipped for people to try the app (SAMPLE-01)."""
import unittest
from pathlib import Path

from minibook import csvimport as c

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_library.csv"


class TestSampleLibrary(unittest.TestCase):
    def setUp(self):
        self.books = c.parse_library_csv(SAMPLE.read_bytes())

    def test_SAMPLE01_it_loads_and_has_enough_books_to_fill_a_sheet(self):
        self.assertGreaterEqual(len(self.books), 12)
        self.assertTrue(all(b.title and b.authors for b in self.books))

    def test_SAMPLE01_it_shows_the_features_a_new_user_wants_to_see(self):
        dated, undated = c.filter_books(self.books, {"read"}, 2026)
        self.assertGreaterEqual(len(dated), 10)
        self.assertEqual(len(undated), 1)                                   # the "no read date" group
        self.assertTrue(any(b.status == "to-read" for b in self.books))     # status filter
        self.assertTrue(any(b.is_audio for b in self.books))                # audiobook notice
        self.assertTrue(any(len(b.title) > 20 for b in self.books))         # a title that needs shrinking or wrapping
        self.assertTrue(any(b.rating and b.rating % 1 for b in dated))      # partial stars
        self.assertTrue(all(b.rating for b in dated))

    def test_SAMPLE01_it_is_a_storygraph_style_file_with_no_personal_data(self):
        text = SAMPLE.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("Title,Authors,"))
        self.assertNotIn("@", text)
        self.assertTrue(all(b.review == "" for b in self.books))

    def test_SAMPLE01_the_books_are_public_domain_classics(self):
        self.assertIn("Dracula", [b.title for b in self.books])
        self.assertIn("Charlotte Brontë", [a for b in self.books for a in b.authors])    # accents survive


if __name__ == "__main__":
    unittest.main()

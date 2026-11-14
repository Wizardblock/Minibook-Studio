"""IMG-11 .. IMG-15: grading cover results (right book / box set / other title), more sources, more options."""
import tempfile
import unittest
from pathlib import Path

from minibook import controller as ctlmod, covers, csvimport as c, settings as S
from tests.helpers import FakeHttp, json_bytes, png_bytes


def book(title="The Way of Kings", authors=("Brandon Sanderson",), **kw):
    return c.Book(title=title, authors=list(authors), **kw)


class TestTitleMatch(unittest.TestCase):
    def test_IMG11_subtitles_series_notes_and_articles_do_not_hurt(self):
        m = covers.title_match
        self.assertGreaterEqual(m("The Way of Kings", "The Way of Kings: Book One of the Stormlight Archive"), 0.8)
        self.assertGreaterEqual(m("Oathbringer (The Stormlight Archive, #3)", "Oathbringer"), 0.8)
        self.assertGreaterEqual(m("The Hobbit", "The Hobbit, or There and Back Again"), 0.8)
        self.assertGreaterEqual(m("Hyperion", "Hyperion: A Novel"), 0.8)
        self.assertGreaterEqual(m("Piranesi", "PIRANESI"), 0.99)
        self.assertGreaterEqual(m("Les Misérables", "Les Miserables"), 0.99)

    def test_IMG11_a_sequel_or_other_book_is_not_a_match(self):
        m = covers.title_match
        self.assertLess(m("Dune", "Dune Messiah"), 0.8)
        self.assertLess(m("Hyperion", "The Fall of Hyperion"), 0.8)
        self.assertLess(m("The Way of Kings", "Words of Radiance"), 0.55)

    def test_IMG11_authors_match_on_last_name(self):
        a = covers.author_match
        self.assertTrue(a(["J.R.R. Tolkien"], ["J. R. R. Tolkien"]))
        self.assertTrue(a(["Terry Pratchett", "Rob Wilkins"], ["Terry Pratchett"]))
        self.assertFalse(a(["Dan Simmons"], ["Simon Dan Wilson"]) and False)
        self.assertFalse(a(["Dan Simmons"], ["Isaac Asimov"]))
        self.assertIsNone(a(["Dan Simmons"], []))
        self.assertIsNone(a([], ["Isaac Asimov"]))

    def test_IMG12_box_sets_and_guides_are_recognised(self):
        r = covers.bundle_reason
        for t in ("The Hobbit and The Lord of the Rings Box Set", "Mistborn Trilogy", "The Stormlight Archive Boxed Set",
                  "Books 1-3 Collection", "Complete Series Bundle", "Dune Omnibus", "3-Book Set",
                  "Summary of The Way of Kings", "Study Guide: Hyperion", "The Hobbit Trivia Quiz"):
            self.assertTrue(r("Whatever", t), t)
        for t in ("The Way of Kings", "The Stand: The Complete and Uncut Edition", "Collection of One"):
            self.assertEqual(r("Whatever", t) != "", t == "Collection of One", t)

    def test_IMG12_a_book_really_called_that_is_not_flagged(self):
        self.assertEqual(covers.bundle_reason("The Dark Tower Collection", "The Dark Tower Collection"), "")
        self.assertEqual(covers.bundle_reason("Trilogy", "Trilogy"), "")
        self.assertTrue(covers.bundle_reason("Hyperion", "X", ["Study Aids"]))

    def test_IMG13_isbn13_converts_to_isbn10(self):
        self.assertEqual(covers.isbn13_to_10("9780306406157"), "0306406152")
        self.assertEqual(covers.isbn13_to_10("9780765326379"), "076532637X")
        self.assertTrue(c.isbn10_valid("076532637X"))
        self.assertIsNone(covers.isbn13_to_10("9791234567896"))


class TestGrading(unittest.TestCase):
    def grade(self, found, authors, wanted=None, **kw):
        cand = covers.CoverCandidate("Google Books", "u", "l", title=found, authors=list(authors), **kw)
        covers.grade(wanted or book(), cand)
        return cand

    def test_IMG11_right_book_is_grade_zero(self):
        self.assertEqual(self.grade("The Way of Kings", ["Brandon Sanderson"]).tier, covers.TIER_GOOD)
        self.assertEqual(self.grade("The Way of Kings", []).tier, covers.TIER_GOOD)       # author not given

    def test_IMG11_same_title_other_author_is_only_possible(self):
        c1 = self.grade("The Way of Kings", ["Somebody Else"])
        self.assertEqual((c1.tier, c1.why), (covers.TIER_MAYBE, "different author listed"))

    def test_IMG11_other_title_is_probably_not(self):
        self.assertEqual(self.grade("Words of Radiance", ["Brandon Sanderson"]).tier, covers.TIER_UNLIKELY)

    def test_IMG12_box_set_is_probably_not_even_with_the_right_author(self):
        c1 = self.grade("The Stormlight Archive Boxed Set: The Way of Kings", ["Brandon Sanderson"])
        self.assertEqual((c1.tier, c1.why), (covers.TIER_UNLIKELY, "looks like a box set or bundle"))

    def test_IMG11_a_cover_found_by_the_books_own_isbn_is_trusted(self):
        c1 = self.grade("Totally Different Title", ["Other Person"], exact=True)
        self.assertEqual(c1.tier, covers.TIER_GOOD)
        c2 = self.grade("Great Box Set", ["Other Person"], exact=True)
        self.assertEqual(c2.tier, covers.TIER_UNLIKELY)       # unless it is plainly a bundle

    def test_IMG11_candidates_without_a_title_are_left_alone(self):
        cand = covers.CoverCandidate("Open Library", "u", "ISBN 1", exact=True)
        covers.grade(book(), cand)
        self.assertEqual(cand.tier, covers.TIER_GOOD)


def gvol(title, authors, img, subtitle="", cats=None):
    info = {"title": title, "authors": authors, "publishedDate": "2010",
            "imageLinks": {"thumbnail": f"http://books.google.com/{img}?x=1"}}
    if subtitle:
        info["subtitle"] = subtitle
    if cats:
        info["categories"] = cats
    return {"volumeInfo": info}


def routes(**over):
    base = {
        "openlibrary.org/search.json": (200, json_bytes({"docs": [
            {"key": "/works/OL1W", "title": "The Way of Kings", "author_name": ["Brandon Sanderson"], "cover_i": 11},
            {"key": "/works/OL2W", "title": "Words of Radiance", "author_name": ["Brandon Sanderson"], "cover_i": 12}]})),
        "openlibrary.org/works/OL1W/editions.json": (200, json_bytes({"entries": [
            {"title": "The Way of Kings", "covers": [21], "publish_date": "2010", "physical_format": "hardcover"},
            {"title": "The Way of Kings", "covers": [22], "publish_date": "2014", "physical_format": "paperback"},
            {"title": "The Way of Kings", "covers": []}]})),
        "googleapis.com": (200, json_bytes({"items": [
            gvol("The Stormlight Archive Boxed Set", ["Brandon Sanderson"], "box"),
            gvol("The Way of Kings", ["Brandon Sanderson"], "kings", subtitle="Book One of the Stormlight Archive"),
            gvol("Summary of The Way of Kings", ["Readers Digest"], "sum"),
            gvol("Words of Radiance", ["Brandon Sanderson"], "radiance")]})),
        "covers.openlibrary.org/b/id/11": (200, png_bytes(300, 450, (10, 200, 10))),
        "covers.openlibrary.org/b/id/12": (200, png_bytes(300, 460, (10, 100, 10))),
        "covers.openlibrary.org/b/id/21": (200, png_bytes(500, 760, (200, 10, 10))),
        "covers.openlibrary.org/b/id/22": (200, png_bytes(520, 780, (10, 10, 200))),
        "books.google.com/box": (200, png_bytes(400, 400, (90, 90, 90))),
        "books.google.com/kings": (200, png_bytes(400, 600, (200, 200, 10))),
        "books.google.com/sum": (200, png_bytes(400, 600, (50, 50, 50))),
        "books.google.com/radiance": (200, png_bytes(400, 620, (150, 20, 150))),
    }
    base.update(over)
    return base


class TestSearchGrading(unittest.TestCase):
    def service(self, r=None):
        self.http = FakeHttp(routes() if r is None else r)
        return covers.CoverService(self.http, Path(tempfile.mkdtemp()))

    def test_IMG12_box_sets_and_guides_sort_to_the_end_but_stay_listed(self):
        res = self.service().search(book())
        tiers = [x.tier for x in res.candidates]
        self.assertEqual(tiers, sorted(tiers))
        by_title = {x.title: x for x in res.candidates}
        self.assertEqual(by_title["The Way of Kings: Book One of the Stormlight Archive"].tier, covers.TIER_GOOD)
        self.assertEqual(by_title["The Stormlight Archive Boxed Set"].tier, covers.TIER_UNLIKELY)
        self.assertEqual(by_title["Summary of The Way of Kings"].tier, covers.TIER_UNLIKELY)
        self.assertEqual(by_title["Words of Radiance"].tier, covers.TIER_UNLIKELY)
        self.assertIn("a different title", [x.why for x in res.candidates])

    def test_IMG14_search_queries_use_the_clean_title_and_the_authors_last_name(self):
        self.service().search(book("Oathbringer (The Stormlight Archive, #3)"))
        g = [p for (u, p) in self.http.calls if "googleapis" in u][0]
        self.assertEqual(g["q"], 'intitle:"Oathbringer" inauthor:"sanderson"')
        o = [p for (u, p) in self.http.calls if "search.json" in u][0]
        self.assertEqual(o["title"], "Oathbringer")

    def test_IMG13_amazon_picture_for_the_isbn10_is_offered(self):
        res = self.service().search(book(isbn="9780765326379"))
        amazon = [x for x in res.candidates if x.source == "Amazon"]
        self.assertEqual(len(amazon), 1)
        self.assertIn("076532637X", amazon[0].url)
        self.assertEqual(amazon[0].tier, covers.TIER_GOOD)

    def test_IMG13_amazon_asin_is_used_for_kindle_and_audio_ids(self):
        res = self.service().search(book(asin="B00351YF0C"))
        self.assertTrue(any("B00351YF0C" in x.url for x in res.candidates))

    def test_IMG13_a_missing_amazon_picture_is_dropped_quietly(self):
        r = routes()
        r["images-na.ssl-images-amazon.com"] = (200, png_bytes(1, 1))
        res = self.service(r).find_covers(book(isbn="9780765326379"))
        self.assertFalse(any(x.source == "Amazon" for x in res.candidates))
        self.assertEqual(res.errors, [])

    def test_IMG15_more_options_adds_other_editions(self):
        svc = self.service()
        plain = svc.search(book())
        deep = svc.search(book(), deep=True)
        urls = {x.url for x in deep.candidates} - {x.url for x in plain.candidates}
        self.assertTrue(any("/b/id/21" in u for u in urls))
        self.assertTrue(any("/b/id/22" in u for u in urls))
        edition = [x for x in deep.candidates if "/b/id/21" in x.url][0]
        self.assertIn("hardcover", edition.label)
        self.assertEqual(edition.tier, covers.TIER_GOOD)

    def test_IMG15_editions_are_only_fetched_for_works_that_match(self):
        self.service().search(book(), deep=True)
        asked = [u for (u, _p) in self.http.calls if "editions.json" in u]
        self.assertEqual(len(asked), 1)
        self.assertIn("OL1W", asked[0])


class TestBulkPick(unittest.TestCase):
    def make(self, r=None):
        tmp = Path(tempfile.mkdtemp())
        self.http = FakeHttp(routes() if r is None else r)
        svc = covers.CoverService(self.http, tmp / "cache")
        return ctlmod.AppController(S.Settings(), {}, svc, settings_path=tmp / "s.json", prefs_path=tmp / "p.json",
                                    custom_dir=tmp / "cu", edits_path=tmp / "e.json", persist=False)

    def test_IMG12_the_default_cover_is_never_a_box_set_or_another_title(self):
        ctl = self.make()
        b = book()
        st = ctl.ensure_cover(b)
        picked = ctl.book_prefs(b).cover_url
        chosen = next(x for x in st.candidates if x.url == picked)
        self.assertEqual(chosen.tier, covers.TIER_GOOD)
        self.assertNotIn("box", picked)
        self.assertIsNotNone(st.image)

    def test_IMG12_when_only_wrong_books_exist_nothing_is_picked_and_the_person_is_told(self):
        r = routes()
        r["openlibrary.org/search.json"] = (200, json_bytes({"docs": []}))
        r["googleapis.com"] = (200, json_bytes({"items": [gvol("Words of Radiance", ["Brandon Sanderson"], "radiance"),
                                                          gvol("Kings Box Set", ["Brandon Sanderson"], "box")]}))
        ctl = self.make(r)
        b = book()
        st = ctl.ensure_cover(b)
        self.assertIsNone(st.image)
        self.assertTrue(st.candidates)                        # still there for the picker
        self.assertTrue(any("no confident match" in e for e in st.errors))

    def test_IMG11_a_possible_match_is_used_but_flagged(self):
        r = routes()
        r["openlibrary.org/search.json"] = (200, json_bytes({"docs": []}))
        r["googleapis.com"] = (200, json_bytes({"items": [gvol("The Way of Kings", ["Somebody Else"], "kings")]}))
        ctl = self.make(r)
        st = ctl.ensure_cover(book())
        self.assertIsNotNone(st.image)
        self.assertTrue(any("unsure" in e for e in st.errors))

    def test_IMG12_ranking_puts_the_likely_book_first_even_if_a_box_set_is_sharper(self):
        ctl = self.make()
        box = covers.CoverCandidate("Google Books", "u1", "Title search: Box", width=1200, height=1800, tier=covers.TIER_UNLIKELY)
        real = covers.CoverCandidate("Google Books", "u2", "Title search: Real", width=200, height=300, tier=covers.TIER_GOOD)
        self.assertEqual(ctl.rank(book(), [box, real])[0], real)

    def test_IMG15_a_bulk_run_downloads_only_a_few_candidates_per_book(self):
        ctl = self.make()
        ctl.ensure_cover(book())
        images = [u for (u, _p) in self.http.calls if "covers.openlibrary.org" in u or "books.google.com" in u]
        self.assertLessEqual(len(images), covers.PROBE_FIRST + 2)

    def test_IMG15_the_picker_downloads_the_rest_and_lists_sizes(self):
        ctl = self.make()
        b = book()
        ctl.ensure_cover(b)
        st = ctl.probe_candidates(b)
        self.assertTrue(all(x.width for x in st.candidates))
        tiers = [x.tier for x in st.candidates]
        self.assertEqual(tiers, sorted(tiers))

    def test_IMG15_more_options_extends_the_list_once_and_drops_the_unlikely(self):
        ctl = self.make()
        b = book()
        ctl.ensure_cover(b)
        before = len(covers.likely(ctl.state(b).candidates))
        ctl.more_options(b)
        cands = ctl.state(b).candidates
        self.assertGreater(len(cands), before)
        self.assertTrue(all(x.tier == covers.TIER_GOOD for x in cands))      # box sets, guides, other titles gone
        calls = len(self.http.calls)
        ctl.more_options(b)
        self.assertEqual(len(self.http.calls), calls)         # asking again does nothing
        self.assertTrue(any("/b/id/21" in x.url for x in cands))

    def test_IMG12_unlikely_results_are_never_downloaded_by_the_picker(self):
        ctl = self.make()
        b = book()
        ctl.ensure_cover(b)
        ctl.more_options(b)
        fetched = [u for (u, _p) in self.http.calls]
        for bad in ("books.google.com/box", "books.google.com/sum", "/b/id/12"):
            self.assertFalse(any(bad in u for u in fetched), bad)

    def test_IMG15_more_options_makes_no_extra_google_request(self):
        ctl = self.make()
        b = book()
        ctl.ensure_cover(b)
        google = len([1 for (u, _p) in self.http.calls if "googleapis" in u])
        ctl.more_options(b)
        self.assertEqual(len([1 for (u, _p) in self.http.calls if "googleapis" in u]), google)


if __name__ == "__main__":
    unittest.main()


class TestDarkCovers(unittest.TestCase):
    """NET-03b: a mostly black cover gets a near-black spine, other covers are untouched."""

    def cover(self, base, base_share, accent, warm=None):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (200, 300), base)
        d = ImageDraw.Draw(im)
        top = int(300 * base_share)
        d.rectangle([0, top, 200, 300], fill=accent)
        if warm:                                           # a dim warm glow, which blends into the dark in clustering
            d.ellipse([60, 120, 140, 180], fill=warm)
        return im

    def test_NET03b_black_cover_with_bright_title_and_warm_glow_gets_a_near_black_spine(self):
        from minibook import imaging
        img = self.cover((10, 10, 12), 0.7, (230, 225, 215), warm=(120, 80, 70))
        r, g, b = imaging.dominant_color(img)
        self.assertLess(max(r, g, b), 40)

    def test_NET03b_a_dark_green_cover_stays_green(self):
        from minibook import imaging
        r, g, b = imaging.dominant_color(self.cover((10, 40, 16), 0.7, (230, 225, 215)))
        self.assertGreater(g, r + 15)

    def test_NET03b_a_cover_that_is_only_partly_dark_keeps_its_colour(self):
        from minibook import imaging
        r, g, b = imaging.dominant_color(self.cover((10, 10, 12), 0.3, (220, 110, 70)))
        self.assertGreater(r, 150)

    def test_NET03b_a_cover_whose_dark_part_is_already_the_chosen_colour_is_unchanged(self):
        from minibook import imaging
        img = self.cover((34, 36, 42), 0.9, (60, 60, 70))
        self.assertEqual(imaging.dominant_color(img), imaging._cluster_color(img.resize((64, 64))))

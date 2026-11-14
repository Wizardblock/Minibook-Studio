"""NET-08 spine colour choice, IMG-17 user-added cover stays in the picker."""
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from minibook import controller as ctlmod, covers, csvimport as c, imaging, net, preview as pv, settings as S
from tests.helpers import FakeHttp, gradient_png, json_bytes, png_bytes


def blocks(*colors, size=(120, 180)):
    """A cover made of horizontal bands, first color on top; sizes are equal."""
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    h = size[1] / len(colors)
    for i, col in enumerate(colors):
        d.rectangle([0, round(i * h), size[0], round((i + 1) * h)], fill=col)
    return im


class TestPalette(unittest.TestCase):
    def test_NET08_most_common_distinct_colors_come_first(self):
        img = Image.new("RGB", (100, 100), (200, 40, 40))                 # red: most of the cover
        ImageDraw.Draw(img).rectangle([0, 0, 100, 25], fill=(40, 80, 200))   # blue
        ImageDraw.Draw(img).rectangle([0, 25, 100, 35], fill=(40, 180, 60))  # green
        p = imaging.palette(img)
        self.assertEqual(len(p), 3)
        self.assertGreater(p[0][0], 150)                  # red first
        self.assertGreater(p[1][2], 150)                  # then blue
        self.assertGreater(p[2][1], 120)                  # then green

    def test_NET08_similar_shades_count_as_one_color(self):
        p = imaging.palette(blocks((200, 40, 40), (205, 45, 42), (198, 38, 44), (40, 80, 200)))
        self.assertEqual(len(p), 2)

    def test_NET08_black_and_white_are_left_out_because_the_picker_offers_them(self):
        p = imaging.palette(blocks((0, 0, 0), (255, 255, 255), (30, 160, 60)))
        self.assertEqual(len(p), 1)
        self.assertGreater(p[0][1], 120)

    def test_NET08_at_most_six_colors(self):
        cols = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30), (200, 30, 200), (30, 200, 200),
                (120, 60, 20), (60, 120, 20)]
        self.assertEqual(len(imaging.palette(blocks(*cols, size=(160, 320)))), 6)

    def test_NET08_a_flat_cover_gives_fewer(self):
        self.assertEqual(len(imaging.palette(Image.new("RGB", (50, 50), (90, 120, 160)))), 1)

    def test_NET08_hex_round_trip_and_bad_text(self):
        self.assertEqual(imaging.to_hex((10, 255, 0)), "#0aff00")
        self.assertEqual(imaging.from_hex("#0aff00"), (10, 255, 0))
        for bad in (None, "", "red", "#12", "#gggggg", "0aff00"):
            self.assertIsNone(imaging.from_hex(bad))


class TestSpineColorOverride(unittest.TestCase):
    def book(self):
        return c.Book("Dune", ["Frank Herbert"])

    def test_NET08_override_sets_spine_and_solid_back(self):
        cover = Image.new("RGB", (400, 600), (20, 120, 40))
        r = net.build_net(self.book(), cover, S.Settings(back_style="complement"), spine_color=(200, 10, 10))
        self.assertEqual(r.image.getpixel((2, 2)), (200, 10, 10))
        self.assertEqual(r.image.getpixel((r.back_w_px + 2, 2)), (200, 10, 10))
        self.assertEqual(r.color, (200, 10, 10))

    def test_NET08_the_bars_of_a_zoomed_out_cover_follow_the_override(self):
        wide = Image.new("RGB", (900, 300), (60, 60, 200))
        r = net.build_net(self.book(), wide, S.Settings(back_style="copy"), zoom=0.1, spine_color=(10, 200, 10))
        front_x = r.back_w_px + r.spine_w_px + 2
        self.assertEqual(r.image.getpixel((front_x, 2)), (10, 200, 10))

    def test_NET08_without_an_override_nothing_changes(self):
        cover = Image.new("RGB", (400, 600), (20, 120, 40))
        a = net.build_net(self.book(), cover, S.Settings())
        b = net.build_net(self.book(), cover, S.Settings(), spine_color=None)
        self.assertEqual(a.image.tobytes(), b.image.tobytes())
        self.assertEqual(a.color, (20, 120, 40))

    def test_NET08_spine_text_color_still_contrasts(self):
        cover = Image.new("RGB", (400, 600), (20, 120, 40))
        dark = net.build_net(self.book(), cover, S.Settings(), spine_color=(5, 5, 5))
        light = net.build_net(self.book(), cover, S.Settings(), spine_color=(250, 250, 250))
        self.assertNotEqual(dark.image.tobytes(), light.image.tobytes())
        spine = lambda r: r.image.crop((r.back_w_px, 0, r.back_w_px + r.spine_w_px, r.image.height)).getcolors(10000)
        self.assertTrue(any(col[0] > 200 for _n, col in spine(dark)))     # white lettering on near-black
        self.assertTrue(any(col[0] < 60 for _n, col in spine(light)))      # dark lettering on near-white


def routes():
    return {"covers.openlibrary.org/b/isbn/": (200, png_bytes(600, 900, (20, 120, 40))),
            "openlibrary.org": (200, json_bytes({"docs": []})),
            "googleapis.com": (200, json_bytes({"items": []})),
            "images-na.ssl-images-amazon.com": (404, b"")}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.make()
        self.book = c.Book(title="Dune", authors=["Frank Herbert"], isbn="9780441013593")

    def make(self):
        svc = covers.CoverService(FakeHttp(routes()), self.tmp / "cache")
        saved = S.load_book_prefs(self.tmp / "p.json")
        self.ctl = ctlmod.AppController(S.Settings(), saved, svc, settings_path=self.tmp / "s.json",
                                        prefs_path=self.tmp / "p.json", custom_dir=self.tmp / "cu",
                                        edits_path=self.tmp / "e.json")
        return self.ctl


class TestControllerColor(Base):
    def test_NET08_choice_is_used_by_the_net_the_preview_and_is_remembered(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        auto = ctl.net_for(b).image.tobytes()
        ctl.set_spine_color(b, (200, 10, 10))
        self.assertEqual(ctl.net_for(b).color, (200, 10, 10))
        self.assertNotEqual(ctl.net_for(b).image.tobytes(), auto)
        self.assertEqual(ctl.book_prefs(b).spine_color, "#c80a0a")
        again = self.make()                                   # a new session
        self.assertEqual(again.book_prefs(b).spine_color, "#c80a0a")

    def test_NET08_choosing_automatic_again_clears_it(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        ctl.set_spine_color(b, (1, 2, 3))
        ctl.set_spine_color(b, None)
        self.assertIsNone(ctl.book_prefs(b).spine_color)
        self.assertEqual(ctl.net_for(b).color, ctl.auto_color(b))

    def test_NET08_preview_redraws_only_the_book_whose_color_changed(self):
        ctl = self.ctl
        for t in ("A", "B"):
            bk = c.Book(title=t, authors=["X"])
            ctl.manual.append(bk) if hasattr(ctl, "manual") else None
        ctl.load_csv(b"Title,Authors\nOne,A\nTwo,B\n", "x.csv")
        books = ctl.selected_books()
        for bk in books:
            ctl.state(bk).image, ctl.state(bk).searched = Image.new("RGB", (300, 450), (30, 90, 30)), True
        ctl.preview_page()
        ctl.set_spine_color(books[0], (200, 0, 0))
        p = ctl.preview_page()
        self.assertEqual((p.nets_built, p.nets_reused), (1, 1))

    def test_NET08_auto_color_matches_what_the_net_would_choose(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        self.assertEqual(ctl.auto_color(b), ctl.net_for(b).color)
        self.assertEqual(ctl.auto_color(b), (20, 120, 40))

    def test_NET08_palette_is_cached_per_cover(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        first = ctl.cover_palette(b)
        self.assertIs(ctl.cover_palette(b), first)
        self.assertEqual(ctl.cover_palette(c.Book(title="No cover yet")), [])

    def test_NET08_unreadable_saved_color_means_automatic(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        ctl.book_prefs(b).spine_color = "banana"
        self.assertEqual(ctl.net_for(b).color, ctl.auto_color(b))


def png(w=300, h=450, color=(10, 90, 200)):
    return png_bytes(w, h, color)


class TestUserAddedCover(Base):
    def test_IMG17_an_uploaded_image_is_in_use_and_listed_as_user_added(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        ctl.set_custom_image(b, png(500, 700))
        self.assertTrue(ctl.state(b).custom)
        cand = ctl.custom_candidate(b)
        self.assertEqual((cand.source, cand.size_text), ("User added", "500×700 px"))
        self.assertEqual(cand.tier, covers.TIER_GOOD)
        self.assertTrue(ctl.custom_active(ctl.book_prefs(b)))

    def test_IMG17_choosing_another_cover_keeps_the_upload_on_file_and_in_the_list(self):
        ctl, b = self.ctl, self.book
        st = ctl.ensure_cover(b)
        ctl.set_custom_image(b, png())
        other = st.candidates[0]
        ctl.choose_candidate(b, other)
        self.assertFalse(ctl.state(b).custom)
        self.assertFalse(ctl.custom_active(ctl.book_prefs(b)))
        self.assertTrue(Path(ctl.book_prefs(b).custom_path).exists())
        self.assertIsNotNone(ctl.custom_candidate(b))

    def test_IMG17_the_upload_can_be_chosen_again_later(self):
        ctl, b = self.ctl, self.book
        st = ctl.ensure_cover(b)
        ctl.set_custom_image(b, png(321, 654))
        ctl.choose_candidate(b, st.candidates[0])
        ctl.use_custom_image(b)
        self.assertTrue(ctl.state(b).custom)
        self.assertEqual(ctl.state(b).image.size, (321, 654))
        self.assertTrue(ctl.custom_active(ctl.book_prefs(b)))

    def test_IMG17_which_cover_is_in_use_survives_a_restart(self):
        ctl, b = self.ctl, self.book
        st = ctl.ensure_cover(b)
        ctl.set_custom_image(b, png(321, 654))
        ctl.choose_candidate(b, st.candidates[0])
        again = self.make()
        again.ensure_cover(b)
        self.assertFalse(again.state(b).custom)                       # the online choice is still the one in use
        self.assertIsNotNone(again.custom_candidate(b))              # and the upload is still offered
        ctl.use_custom_image(b)
        third = self.make()
        third.ensure_cover(b)
        self.assertTrue(third.state(b).custom)
        self.assertEqual(third.state(b).image.size, (321, 654))

    def test_IMG17_a_file_saved_by_an_older_version_still_counts_as_in_use(self):
        ctl, b = self.ctl, self.book
        ctl.set_custom_image(b, png(111, 222))
        p = ctl.book_prefs(b)
        self.assertIsNone(p.cover_url)                                 # how older versions stored it
        again = self.make()
        again.ensure_cover(b)
        self.assertTrue(again.state(b).custom)

    def test_IMG17_candidate_images_load_through_one_path(self):
        ctl, b = self.ctl, self.book
        ctl.set_custom_image(b, png(333, 444))
        cand = ctl.custom_candidate(b)
        self.assertEqual(ctl.load_candidate_image(cand).size, (333, 444))

    def test_IMG17_no_upload_means_no_candidate_and_using_it_is_an_error(self):
        ctl, b = self.ctl, self.book
        self.assertIsNone(ctl.custom_candidate(b))
        with self.assertRaises(covers.CoverError):
            ctl.use_custom_image(b)

    def test_IMG17_uploading_again_replaces_the_previous_upload(self):
        ctl, b = self.ctl, self.book
        ctl.set_custom_image(b, png(100, 150))
        ctl.set_custom_image(b, png(200, 300))
        self.assertEqual(ctl.custom_candidate(b).size_text, "200×300 px")


if __name__ == "__main__":
    unittest.main()


class TestAutoColorIsStable(unittest.TestCase):
    def test_NET08_a_cover_whose_pick_used_to_change_with_resolution(self):
        cover = Image.open(Path(__file__).parent / "data" / "auto_color_tie.png").convert("RGB")
        b = c.Book("X", ["Y"])
        seen = {net.build_net(b, cover, S.Settings(dpi=d)).color for d in (100, 300)}
        self.assertEqual(len(seen), 1)

    def test_NET08_auto_color_is_the_same_at_every_print_and_preview_resolution(self):
        # two near-equal color areas: the old per-resolution pick flipped between them
        cover = Image.new("RGB", (600, 900), (190, 160, 110))
        ImageDraw.Draw(cover).rectangle([0, 0, 600, 430], fill=(70, 100, 60))
        ImageDraw.Draw(cover).rectangle([0, 430, 600, 470], fill=(120, 40, 40))
        b = c.Book("X", ["Y"])
        seen = {net.build_net(b, cover, S.Settings(dpi=d)).color for d in (60, 100, 110, 165, 220, 300)}
        self.assertEqual(len(seen), 1)

    def test_NET08_controller_auto_matches_the_net_and_the_preview_after_clicking_auto(self):
        tmp = Path(tempfile.mkdtemp())
        ctl = ctlmod.AppController(S.Settings(), {}, None, settings_path=tmp / "s", prefs_path=tmp / "p",
                                   custom_dir=tmp / "c", edits_path=tmp / "e")
        b = c.Book("X", ["Y"])
        cover = Image.new("RGB", (600, 900), (190, 160, 110))
        ImageDraw.Draw(cover).rectangle([0, 0, 600, 430], fill=(70, 100, 60))
        ctl.state(b).image = cover
        swatch = ctl.auto_color(b)
        ctl.set_spine_color(b, (1, 2, 3))
        ctl.set_spine_color(b, None)
        for dpi in (110, 220, 300):
            ctl.settings.dpi = dpi
            self.assertEqual(ctl.net_for(b).color, swatch)


class TestRealGoodreadsExport(unittest.TestCase):
    def test_DATA11_a_real_goodreads_export_reads_dates_ratings_and_isbns(self):
        data = (Path(__file__).parent / "data" / "goodreads_sample.csv").read_bytes()
        books = c.parse_library_csv(data)
        self.assertEqual([b.title for b in books], ["The Hitchhiker's Guide to the Galaxy", "The Martian"])
        self.assertEqual([b.rating for b in books], [3.75, 4.5])
        self.assertEqual(str(books[0].read_date), "2026-10-30")
        self.assertEqual(books[1].isbn, "9780804139021")
        self.assertIsNone(books[0].isbn)                  # Goodreads left it blank: found by title and author
        self.assertEqual([b.status for b in books], ["read", "read"])


class TestSharpnessIgnoresPrintDpi(unittest.TestCase):
    def test_IMG05_a_cover_is_not_called_low_res_just_because_the_print_dpi_is_600(self):
        from minibook import imaging as im
        w, h = 0.81 * 25.4, 1.25 * 25.4
        self.assertEqual(im.quality(324, 500, w, h, 600)[0], "good")      # about 400 dpi at print size
        self.assertEqual(im.quality(324, 500, w, h, 300)[0], "good")
        self.assertEqual(im.quality(287, 500, w, h, 600)[0], "good")      # 354 dpi
        self.assertEqual(im.quality(128, 199, w, h, 600)[0], "low")       # about 158 dpi is still low
        self.assertEqual(im.quality(128, 199, w, h, 300)[0], "low")

    def test_IMG05_a_draft_print_still_asks_for_less(self):
        from minibook import imaging as im
        w, h = 0.81 * 25.4, 1.25 * 25.4
        self.assertEqual(im.quality(128, 199, w, h, 150)[0], "good")      # 158 dpi is enough for a 150 dpi draft

    def test_IMG05_the_picker_and_list_badges_use_the_same_rule(self):
        tmp = Path(tempfile.mkdtemp())
        ctl = ctlmod.AppController(S.Settings(dpi=600, width_mm=0.81 * 25.4, height_mm=1.25 * 25.4), {}, None,
                                   settings_path=tmp / "s", prefs_path=tmp / "p", custom_dir=tmp / "c",
                                   edits_path=tmp / "e")
        cand = covers.CoverCandidate("Open Library", "u", "x")
        cand.width, cand.height = 324, 500
        self.assertEqual(ctl.candidate_info(cand)[0], "good")
        b = c.Book("X", ["Y"])
        ctl.state(b).image = Image.new("RGB", (287, 500))
        self.assertEqual(ctl.status(b).quality, "good")


class TestColorBelongsToItsCover(Base):
    def other_cover(self):
        return Image.new("RGB", (300, 450), (200, 190, 40))

    def test_NET08_a_color_chosen_for_one_cover_is_not_used_on_another(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        mine = ctl.state(b).image
        ctl.set_spine_color(b, (200, 10, 10))
        self.assertEqual(ctl.net_for(b).color, (200, 10, 10))
        ctl.state(b).image = self.other_cover()                       # another edition turns up next time
        self.assertIsNone(ctl.spine_override(b))
        self.assertEqual(ctl.net_for(b).color, ctl.auto_color(b))
        self.assertEqual(ctl.net_for(b).color, (200, 190, 40))
        ctl.state(b).image = mine                                    # and the first one is still remembered
        self.assertEqual(ctl.net_for(b).color, (200, 10, 10))

    def test_NET08_a_color_saved_by_an_earlier_version_is_ignored(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        ctl.book_prefs(b).spine_color = "#c80a0a"                   # no cover recorded with it
        self.assertIsNone(ctl.spine_override(b))
        self.assertEqual(ctl.net_for(b).color, ctl.auto_color(b))
        self.assertEqual([x.spine_color for x in ctl.preview_items()] or [None], [None] if ctl.preview_items() else [None])

    def test_NET08_reopening_with_a_different_cover_found_gives_automatic_and_fresh_swatches(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        ctl.set_spine_color(b, (1, 2, 3))
        again = self.make()
        again.ensure_cover(b)
        again.state(b).image = self.other_cover()
        self.assertEqual(again.net_for(b).color, (200, 190, 40))
        self.assertEqual(again.cover_palette(b)[0], (200, 190, 40))

    def test_NET08_the_choice_survives_the_cover_being_resaved_as_jpeg(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        ctl.set_spine_color(b, (200, 10, 10))
        buf = io.BytesIO()
        ctl.state(b).image.save(buf, "JPEG", quality=70)
        ctl.state(b).image = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
        self.assertEqual(ctl.net_for(b).color, (200, 10, 10))

    def test_NET08_clearing_the_choice_forgets_the_cover_too(self):
        ctl, b = self.ctl, self.book
        ctl.ensure_cover(b)
        ctl.set_spine_color(b, (1, 2, 3))
        ctl.set_spine_color(b, None)
        p = ctl.book_prefs(b)
        self.assertEqual((p.spine_color, p.spine_cover), (None, None))

    def test_NET08_fingerprints_tell_pictures_apart(self):
        a = imaging.fingerprint(Image.new("RGB", (100, 150), (200, 10, 10)))
        self.assertTrue(imaging.same_picture(a, imaging.fingerprint(Image.new("RGB", (400, 600), (200, 10, 10)))))
        self.assertFalse(imaging.same_picture(a, imaging.fingerprint(Image.new("RGB", (100, 150), (10, 200, 10)))))
        for bad in (None, "", "zz", "00"):
            self.assertFalse(imaging.same_picture(a, bad))
            self.assertFalse(imaging.same_picture(bad, a))

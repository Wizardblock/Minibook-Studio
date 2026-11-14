"""All GUI behavior, with no GUI framework in sight (GUI-* requirements).

The NiceGUI view only calls these methods and draws what they return, so everything
here is testable without a window.
"""
from __future__ import annotations

import io
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from PIL import Image

from . import covers, csvimport as c, imaging, net, pdfexport, preview as pv, settings as S, svgexport, testprint, units, workspace


@dataclass
class CoverState:
    image: Image.Image | None = None
    candidates: list[covers.CoverCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    searched: bool = False
    custom: bool = False
    deep: bool = False            # "more options" (other editions, looser search) have been added
    probed: bool = False          # every candidate has been downloaded and sized


@dataclass
class BookStatus:
    """What the review row shows for one book."""
    has_cover: bool
    quality: str | None          # good / ok / low / None
    effective_dpi: float | None
    size_text: str
    warnings: list[str]


MAX_ZOOM = 4.0
YEAR_ALL = 0                       # the "All years" choice in the year box
STATUS_OPTIONS = {c.ALL_STATUSES: "All statuses", "read": "Read", "currently-reading": "Currently reading",
                  "to-read": "To read", "none": "No status"}


def default_output_dir() -> str:
    docs = Path.home() / "Documents"
    return str(docs if docs.is_dir() else Path.home())


class AppController:
    def __init__(self, settings: S.Settings | None = None, prefs: dict[str, S.BookPrefs] | None = None,
                 cover_service: covers.CoverService | None = None, *,
                 settings_path: Path | None = None, prefs_path: Path | None = None,
                 custom_dir: Path | None = None, edits_path: Path | None = None, persist: bool = True):
        self.settings = settings or S.Settings()
        self.prefs = prefs if prefs is not None else {}
        self.svc = cover_service
        self.settings_path, self.prefs_path = settings_path, prefs_path
        self.custom_dir = custom_dir or (S.config_dir() / "custom_covers")
        self.edits_path = edits_path
        self.persist = persist
        self.edits = self._load_edits()
        if self.svc is not None:
            self.svc.set_google_key(self.settings.google_api_key)
        self.all_books: list[c.Book] = []
        self.manual: list[c.Book] = []
        self.dated: list[c.Book] = []
        self.undated: list[c.Book] = []
        self.year: int | None = None
        self.statuses: set[str] = {"read"}
        self.cover_state: dict[str, CoverState] = {}
        self._palettes: dict[int, tuple[Image.Image, list]] = {}      # id(cover) -> (cover, its color palette)
        self._fingerprints: dict[int, tuple[Image.Image, str]] = {}   # id(cover) -> (cover, its fingerprint)
        self.csv_name: str = ""
        self.pending: set[str] = set()       # ids of books edited since their cover was last looked up
        self._thumbs: dict[tuple[str, int], bytes] = {}
        self.preview = pv.PreviewEngine()

    # -- settings -----------------------------------------------------------------
    def update_settings(self, **changes) -> list[str]:
        """Apply changes, return validation problems. Only valid settings are written to disk (SET-01)."""
        old_key = self.settings.google_api_key
        self.settings = replace(self.settings, **changes)
        if "google_api_key" in changes and self.svc is not None:
            self.svc.set_google_key(self.settings.google_api_key)
            if self.settings.google_api_key.strip() != old_key.strip():
                self._search_again_for_google()
        problems = self.settings.validate()
        if not problems and self.persist:
            S.save_settings(self.settings, self.settings_path)
        return problems

    def export_settings(self) -> str:
        """Text of a shareable settings file (SET-04)."""
        return S.export_settings_text(self.settings)

    def import_settings(self, text: str | bytes) -> S.ImportResult:
        """Apply a settings file. The Google key and save folder are kept; nothing changes if it is refused."""
        res = S.import_settings_text(text, self.settings)
        if res.settings is not None:
            self.settings = res.settings
            if self.persist:
                S.save_settings(self.settings, self.settings_path)
        return res

    def _search_again_for_google(self) -> None:
        """A new key changes what Google answers, so books looked up earlier are searched again the
        next time covers are fetched. Chosen covers, custom images and crops are kept."""
        for st in self.cover_state.values():
            if st.searched and not st.custom:
                st.searched = False

    def apply_scale(self, real_w_in: float, real_h_in: float, real_t_in: float, scale: float = 12.0) -> list[str]:
        """Scale calculator (DIM-04): real book size -> board size."""
        w, h, t = units.scale_dimensions(real_w_in, real_h_in, real_t_in, scale)
        return self.update_settings(size_mode="width", width_mm=units.in_to_mm(w),
                                    height_mm=units.in_to_mm(h), thickness_mm=units.in_to_mm(t))

    def show(self, value_mm: float) -> float:
        return units.from_mm(value_mm, self.settings.unit, self.settings.dpi)

    def hide(self, value: float) -> float:
        return units.to_mm(value, self.settings.unit, self.settings.dpi)

    def wrap_available(self) -> bool:
        """Two title lines only fit if the spine is thick enough for the smallest text (NET-05b)."""
        from . import spine
        return spine.wrap_possible(self.settings.thickness_mm, self.settings.spine_min_font_pt)

    @property
    def output_dir(self) -> Path:
        return Path(self.settings.output_dir or default_output_dir())

    # -- import / filter / select (DATA-*) ---------------------------------------------
    def load_csv(self, data: bytes, name: str = "") -> dict:
        """Parse a StoryGraph or Goodreads export. Raises CsvFormatError with a readable message (DATA-01)."""
        self.all_books = c.parse_library_csv(data)
        for b in self.all_books:
            e = self.edits.get(b.source_id)
            if e:
                try:
                    c.apply_edit(b, e.get("title", b.title), e.get("author", b.author), e.get("isbn", ""),
                                 read_date=e["read_date"] if "read_date" in e else c.UNCHANGED,
                                 rating=e["rating"] if "rating" in e else c.UNCHANGED)
                except ValueError:
                    pass
        self.csv_name = name
        years = c.available_years(self.all_books)
        self.cover_state.clear()
        self.apply_filter(year=years[0] if years else None, statuses={"read"})
        return {"books": len(self.all_books), "years": years}

    # -- the whole workspace in one file (WS-*) -----------------------------------------------
    def save_workspace(self) -> bytes:
        return workspace.save(self)

    def open_workspace(self, data: bytes) -> dict:
        """Replace the books, choices, covers and output settings with a saved workspace."""
        return workspace.load(self, data)

    def workspace_filename(self) -> str:
        stem = Path(self.csv_name).stem if self.csv_name else "minibook"
        return f"{stem}{workspace.EXTENSION}"

    def apply_filter(self, year: int | None, statuses: set[str] | None = None) -> None:
        self.year = year
        self.statuses = set(statuses) if statuses else {"read"}
        self.dated, self.undated = c.filter_books(self.all_books, self.statuses, year)
        c.apply_default_selection(self.dated, self.undated)
        if year is None:                      # "All years" means all: books with no read date count too
            for b in self.undated:
                b.selected = True
        self.dated = c.sort_books(self.dated, self.settings.sort)
        self.undated = c.sort_books(self.undated, self.settings.sort)
        c.flag_duplicates(self.visible())

    def filter_from_choices(self, year_choice: int | None, status_choices: list[str] | None) -> None:
        """Apply the filter boxes as the view shows them: 0 = all years; '*' = all statuses; 'none' = blank."""
        year = year_choice if year_choice not in (None, YEAR_ALL) else None
        choices = list(status_choices or [])
        if c.ALL_STATUSES in choices:
            statuses = {c.ALL_STATUSES}
        else:
            statuses = {("" if x == "none" else x) for x in choices} or {"read"}
        self.apply_filter(year, statuses)

    def year_choice(self) -> int:
        return self.year if self.year is not None else YEAR_ALL

    def status_choices(self) -> list[str]:
        if c.ALL_STATUSES in self.statuses:
            return [c.ALL_STATUSES]
        return sorted("none" if x == "" else x for x in self.statuses)

    def add_manual(self, title: str, author: str = "", isbn: str = "", read_date: str = "",
                   rating=None) -> c.Book:
        b = c.manual_book(title, author, isbn, read_date=read_date, rating=rating)
        self.manual.append(b)
        c.flag_duplicates(self.visible())
        return b

    def remove_manual(self, book_id: str) -> None:
        self.manual = [b for b in self.manual if b.id != book_id]

    def visible(self) -> list[c.Book]:
        return self.manual + self.dated + self.undated

    # -- editing (DATA-10) --------------------------------------------------------------
    def _load_edits(self) -> dict[str, dict]:
        path = self.edits_path or (S.config_dir() / "book_edits.json")
        if not self.persist:
            return {}
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}

    def edit_book(self, book: c.Book, title: str, author: str, isbn: str,
                  read_date=c.UNCHANGED, rating=c.UNCHANGED) -> c.Book:
        """Change a book's title, author, ISBN, date read or star rating (DATA-10, DATA-12).

        A new title, author or ISBN makes per-book choices follow the book and the cover is searched again;
        changing only the date or rating leaves the cover alone. Edits to books from the CSV are remembered,
        so they survive re-importing the same file. A new date can move the book between the year filter's
        groups; everyone else keeps their ticks.
        """
        old_id = book.id
        who_before = (book.title, tuple(book.authors), book.isbn, book.asin)
        date_before = book.read_date
        had_custom = self.custom_active(self.prefs.get(old_id))
        c.apply_edit(book, title, author, isbn, read_date=read_date, rating=rating)
        new_id = book.id
        identity_changed = who_before != (book.title, tuple(book.authors), book.isbn, book.asin)
        if identity_changed:
            self.pending.discard(old_id)
            self.pending.add(new_id)
        if book.source == "csv":
            self.edits[book.source_id] = {"title": book.title, "author": book.author,
                                          "isbn": book.isbn or book.asin or "",
                                          "read_date": str(book.read_date) if book.read_date else "",
                                          "rating": book.rating}
            if self.persist:
                S._atomic_write(Path(self.edits_path or (S.config_dir() / "book_edits.json")),
                                json.dumps(self.edits, indent=2))
        if new_id != old_id:
            prefs = self.prefs.pop(old_id, None)
            if prefs is not None:
                if not had_custom:
                    prefs = S.BookPrefs()      # the remembered online choice belonged to the old details
                self.prefs[new_id] = prefs
            old_state = self.cover_state.pop(old_id, None)
            if old_state is not None and had_custom:
                self.cover_state[new_id] = old_state
            self._save_prefs()
        elif identity_changed:
            # same id (e.g. only the author's case changed): still look for covers again
            self.cover_state.pop(old_id, None)
        if book.read_date != date_before and book.source == "csv":
            ticks = {id(x): x.selected for x in self.all_books}
            self.apply_filter(self.year, self.statuses)
            for x in self.all_books:
                if x is not book and id(x) in ticks:
                    x.selected = ticks[id(x)]
        c.flag_duplicates(self.visible())
        self.resort()
        return book

    def edited_books(self) -> list[c.Book]:
        """Books edited since their cover was last looked up (the "Fetch edited" button)."""
        return [b for b in self.visible() if b.id in self.pending]

    def needs_cover(self, book: c.Book) -> bool:
        st = self.cover_state.get(book.id)
        return st is None or not st.searched

    # -- small images for the list, served by URL so the browser can cache them -----------------------
    def thumb_url(self, book: c.Book) -> str | None:
        st = self.cover_state.get(book.id)
        if st is None or st.image is None:
            return None
        return f"/thumb/{book.id}?v={id(st.image):x}"

    def thumb_bytes(self, book_id: str) -> bytes | None:
        st = self.cover_state.get(book_id)
        if st is None or st.image is None:
            return None
        key = (book_id, id(st.image))
        if key not in self._thumbs:
            for k in [k for k in self._thumbs if k[0] == book_id]:
                del self._thumbs[k]
            img = st.image.convert("RGB")
            img.thumbnail((120, 180))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=82)
            self._thumbs[key] = buf.getvalue()
        return self._thumbs[key]

    def book_by_id(self, book_id: str) -> c.Book | None:
        return next((b for b in self.visible() if b.id == book_id), None)

    def set_selected(self, book_id: str, value: bool) -> None:
        for b in self.visible():
            if b.id == book_id:
                b.selected = value

    def select_all(self, value: bool, group: str = "all") -> None:
        pool = {"all": self.visible(), "dated": self.dated, "undated": self.undated,
                "manual": self.manual}[group]
        for b in pool:
            b.selected = value

    def selected_books(self) -> list[c.Book]:
        """Chosen books in print order (DATA-07)."""
        return c.sort_books([b for b in self.visible() if b.selected], self.settings.sort)

    def resort(self) -> None:
        self.dated = c.sort_books(self.dated, self.settings.sort)
        self.undated = c.sort_books(self.undated, self.settings.sort)

    # -- per-book choices (SET-03) -------------------------------------------------------
    def book_prefs(self, book: c.Book) -> S.BookPrefs:
        return self.prefs.setdefault(book.id, S.BookPrefs())

    def _save_prefs(self) -> None:
        if self.persist:
            S.save_book_prefs(self.prefs, self.prefs_path)

    # -- covers (IMG-*) ----------------------------------------------------------------
    def state(self, book: c.Book) -> CoverState:
        return self.cover_state.setdefault(book.id, CoverState())

    def ensure_cover(self, book: c.Book, force_search: bool = False) -> CoverState:
        """Find a cover for the book: remembered custom image, remembered choice, else the best match."""
        st = self.state(book)
        if st.searched and not force_search:
            return st
        self.pending.discard(book.id)
        p = self.book_prefs(book)
        st.searched = True
        st.errors = []
        if self.custom_active(p) and Path(p.custom_path).exists() and not force_search:
            try:
                st.image = covers.load_local_image(p.custom_path)
                st.custom = True
                return st
            except covers.CoverError as e:
                st.errors.append(f"saved custom image unusable: {e}")
        st.custom = False
        if self.svc is None:
            st.errors.append("offline: cover lookup is switched off")
            return st
        try:
            res = self.svc.find_covers(book, probe="some")
        except Exception as e:  # defensive: never let one book stop the run (IMG-10)
            st.errors.append(f"{type(e).__name__}: {e}")
            return st
        st.candidates = self.rank(book, res.candidates)
        st.deep = st.probed = False
        st.errors += res.errors
        if self.svc is not None:
            for note in self.svc.notices:
                if note not in st.errors:
                    st.errors.append(note)
        pick = next((x for x in st.candidates if x.url == p.cover_url), None)
        if pick is None:
            # Never pick a result that is probably another book (box set, guide...). A grade-1 "possible"
            # match is used, and flagged, only when there is nothing better.
            pick = next((x for x in st.candidates if x.tier <= covers.TIER_MAYBE and x.width), None)
            if pick is not None:
                p.cover_url = pick.url
                self._save_prefs()
                if pick.tier == covers.TIER_MAYBE:
                    st.errors.append(f"unsure this is the right book ({pick.why}): check with Cover")
            elif st.candidates:
                st.errors.append("no confident match: open Cover to choose one of the other results")
        if pick is not None:
            try:
                st.image = self.svc.load_image(pick)
            except covers.CoverError as e:
                st.errors.append(str(e))
        return st

    def probe_candidates(self, book: c.Book) -> CoverState:
        """Download every candidate so the picker can show sizes and drop dead links and duplicates."""
        st = self.state(book)
        if self.svc is None or st.probed:
            return st
        chosen = self.book_prefs(book).cover_url
        shown = covers.likely(st.candidates)           # box sets and other titles are not shown, so not downloaded
        keep = self.svc.probe(shown)
        # the picture currently in use stays listed even if it is a duplicate of another
        if chosen and not any(x.url == chosen for x in keep):
            keep += [x for x in st.candidates if x.url == chosen]
        st.candidates = self.rank(book, keep)
        st.probed = True
        return st

    def more_options(self, book: c.Book) -> CoverState:
        """Look harder (other editions of the book, a looser search) and add what is new. Once per book."""
        st = self.state(book)
        if self.svc is None or st.deep:
            return st
        st.deep = True
        try:
            res = self.svc.find_covers(book, probe="all", deep=True, likely_only=True)
        except Exception as e:
            st.errors.append(f"more options: {type(e).__name__}: {e}")
            return self.probe_candidates(book)
        known = {x.url for x in st.candidates}
        st.candidates = self.rank(book, st.candidates + [x for x in res.candidates if x.url not in known])
        st.probed = False
        return self.probe_candidates(book)

    def score(self, book: c.Book, cand: covers.CoverCandidate) -> int:
        """Higher = a better default pick: sharp, the right book, not square audiobook art (IMG-03b)."""
        level, _dpi, _lossy = self.candidate_info(cand)
        pts = {"good": 20, "ok": 10, "low": 0}.get(level, 5)
        label = cand.label.lower()
        if cand.label.startswith(("ISBN ", "ISBN match")) and not book.is_audio:
            pts += 5
        title = re.sub(r"[^a-z0-9]+", " ", book.title.lower()).strip()
        shown = re.sub(r"[^a-z0-9]+", " ", label.split(": ", 1)[-1]).strip()
        shown = re.sub(r" \d{4}$", "", shown)
        if title and shown == title:
            pts += 4
        elif title and (title in shown or shown in title) and shown:
            pts += 1
        if cand.is_squarish:
            pts -= 6
        return pts

    def rank(self, book: c.Book, cands: list[covers.CoverCandidate]) -> list[covers.CoverCandidate]:
        """Best first; ties keep the search order."""
        return sorted(cands, key=lambda x: (x.tier, -self.score(book, x)))

    def choose_candidate(self, book: c.Book, cand: covers.CoverCandidate) -> None:
        if self.svc is None:
            raise covers.CoverError("cover lookup is switched off")
        st = self.state(book)
        st.image = self.svc.load_image(cand)
        st.custom = False
        p = self.book_prefs(book)
        p.cover_url = cand.url               # an uploaded image stays on file and in the list, just not in use
        p.zoom, p.pan_x, p.pan_y = 1.0, 0.5, 0.5
        self._save_prefs()

    @staticmethod
    def custom_active(p: S.BookPrefs | None) -> bool:
        """An uploaded image is the cover in use when one is on file and no online cover is chosen."""
        return bool(p and p.custom_path and not p.cover_url)

    def custom_candidate(self, book: c.Book) -> covers.CoverCandidate | None:
        """The uploaded image as a picker entry ("User added"), sized like any other cover."""
        p = self.book_prefs(book)
        if not (p.custom_path and Path(p.custom_path).exists()):
            return None
        cand = covers.CoverCandidate("User added", Path(p.custom_path).as_uri(), "Your image", title="Your image")
        try:
            cand.width, cand.height = covers.load_local_image(p.custom_path).size
        except covers.CoverError:
            return None
        return cand

    def load_candidate_image(self, cand: covers.CoverCandidate) -> Image.Image:
        """Picture for a picker entry, whether it came from the internet or from the user."""
        if cand.source == "User added":
            img = covers.load_local_image(urllib.request.url2pathname(urllib.parse.urlparse(cand.url).path))
            cand.width, cand.height = img.size
            return img
        if self.svc is None:
            raise covers.CoverError("cover lookup is switched off")
        return self.svc.load_image(cand)

    def use_custom_image(self, book: c.Book) -> None:
        """Switch back to the uploaded image."""
        p = self.book_prefs(book)
        if not (p.custom_path and Path(p.custom_path).exists()):
            raise covers.CoverError("no uploaded image for this book")
        st = self.state(book)
        st.image, st.custom = covers.load_local_image(p.custom_path), True
        p.cover_url = None
        p.zoom, p.pan_x, p.pan_y = 1.0, 0.5, 0.5
        self._save_prefs()

    # -- spine / back color (NET-08) ---------------------------------------------------------
    def cover_palette(self, book: c.Book) -> list[tuple[int, int, int]]:
        st = self.state(book)
        if st.image is None:
            return []
        hit = self._palettes.get(id(st.image))
        if hit is None or hit[0] is not st.image:
            hit = (st.image, imaging.palette(st.image))
            self._palettes[id(st.image)] = hit
        return hit[1]

    def auto_color(self, book: c.Book) -> tuple[int, int, int] | None:
        """The color the app picks by itself for this cover and crop."""
        st = self.state(book)
        if st.image is None:
            return None
        p = self.book_prefs(book)
        cover_w, _spine, height = net.board_pixels(self.settings)
        return net.auto_color(st.image, cover_w / height, p.zoom, p.pan_x, p.pan_y)

    def cover_fingerprint(self, book: c.Book) -> str | None:
        st = self.state(book)
        if st.image is None:
            return None
        hit = self._fingerprints.get(id(st.image))
        if hit is None or hit[0] is not st.image:
            hit = (st.image, imaging.fingerprint(st.image))
            self._fingerprints[id(st.image)] = hit
        return hit[1]

    def spine_override(self, book: c.Book) -> tuple[int, int, int] | None:
        """The color chosen for this book's cover, or None for automatic. A color picked while another
        cover was showing (an earlier visit, another edition) is not applied to this one."""
        p = self.book_prefs(book)
        if not p.spine_color or not p.spine_cover:
            return None
        if not imaging.same_picture(p.spine_cover, self.cover_fingerprint(book)):
            return None
        return imaging.from_hex(p.spine_color)

    def set_spine_color(self, book: c.Book, color: tuple[int, int, int] | None) -> None:
        """None = automatic. The spine and the solid back share this color; it is kept for this cover only."""
        p = self.book_prefs(book)
        fp = self.cover_fingerprint(book)
        if color and fp:
            p.spine_color, p.spine_cover = imaging.to_hex(color), fp
        else:
            p.spine_color = p.spine_cover = None
        self._save_prefs()

    def set_custom_image(self, book: c.Book, data: bytes) -> None:
        """Custom upload (IMG-07). The image is copied into the app's config folder so it survives restarts."""
        img = covers.load_local_image(io.BytesIO(data))
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        path = self.custom_dir / f"{book.id}.png"
        img.save(path, "PNG")
        st = self.state(book)
        st.image, st.custom, st.searched = img, True, True
        p = self.book_prefs(book)
        p.custom_path, p.cover_url = str(path), None      # in use now; choosing another cover keeps the file
        p.zoom, p.pan_x, p.pan_y = 1.0, 0.5, 0.5
        self._save_prefs()

    def set_crop(self, book: c.Book, zoom: float | None = None, pan_x: float | None = None,
                 pan_y: float | None = None) -> None:
        """Manual crop (IMG-09). Values are clamped so the window always stays inside the image."""
        p = self.book_prefs(book)
        if zoom is not None:
            p.zoom = min(MAX_ZOOM, max(self.zoom_min(book), float(zoom)))
        if pan_x is not None:
            p.pan_x = min(1.0, max(0.0, float(pan_x)))
        if pan_y is not None:
            p.pan_y = min(1.0, max(0.0, float(pan_y)))
        self._save_prefs()

    def zoom_min(self, book: c.Book) -> float:
        """Smallest zoom for this cover: the whole image just visible (IMG-09b). 1.0 until a cover is loaded."""
        st = self.state(book)
        if st.image is None:
            return 1.0
        s = self.settings
        return imaging.min_zoom(st.image.width, st.image.height, s.board_width_mm / s.height_mm)

    def reset_crop(self, book: c.Book) -> None:
        self.set_crop(book, 1.0, 0.5, 0.5)

    def candidate_info(self, cand: covers.CoverCandidate) -> tuple[str, float | None, bool]:
        """(quality, effective dpi, crop-loss warning) for the picker badge (IMG-04, IMG-05, IMG-06)."""
        if not (cand.width and cand.height):
            return "unknown", None, False
        s = self.settings
        level, dpi = imaging.quality(cand.width, cand.height, s.board_width_mm, s.height_mm, s.dpi)
        lossy = imaging.crop_loss(cand.width, cand.height, s.board_width_mm / s.height_mm) > imaging.CROP_LOSS_WARN
        return level, dpi, lossy

    def status(self, book: c.Book) -> BookStatus:
        st = self.state(book)
        if st.image is None:
            warn = ["no cover yet"] if not st.searched else (st.errors or ["no cover found"])
            return BookStatus(False, None, None, "", list(warn))
        s, p = self.settings, self.book_prefs(book)
        level, dpi = imaging.quality(st.image.width, st.image.height, s.board_width_mm, s.height_mm, s.dpi, p.zoom)
        warns = []
        if abs(p.zoom - 1.0) < 1e-6 and imaging.crop_loss(st.image.width, st.image.height,
                                               s.board_width_mm / s.height_mm) > imaging.CROP_LOSS_WARN:
            warns.append("center crop loses a lot of the image: adjust the crop")
        if level == "low":
            warns.append(f"low resolution ({dpi:.0f} dpi)")
        return BookStatus(True, level, dpi, f"{st.image.width}×{st.image.height} px", warns)

    # -- previews and output -----------------------------------------------------------------
    def preview_items(self) -> list[pv.PreviewInput]:
        """Selected books in print order with whatever cover each has right now (EXP-07)."""
        out = []
        for b in self.selected_books():
            st = self.cover_state.get(b.id)
            p = self.book_prefs(b)
            out.append(pv.PreviewInput(b, st.image if st else None, p.zoom, p.pan_x, p.pan_y,
                                       self.spine_override(b)))
        return out

    def preview_page(self, page: int = 0, is_current=None) -> pv.PreviewPage | None:
        """One sheet of the preview, or None when nothing is selected. Raises LayoutError for bad settings."""
        items = self.preview_items()
        if not items:
            return None
        return self.preview.render_page(items, self.settings, page, is_current)

    def preview_book_at(self, page: int, x_px: float, y_px: float) -> c.Book | None:
        """The book under a click on the preview image (EXP-07b)."""
        books = self.selected_books()
        i = self.preview.hit_test(self.settings, len(books), page, x_px, y_px)
        return books[i] if i is not None else None

    def crop_preview(self, book: c.Book, dpi: int = 120) -> Image.Image | None:
        """The front cover as it will print (live crop preview)."""
        st = self.state(book)
        if st.image is None:
            return None
        s, p = self.settings, self.book_prefs(book)
        w = units.mm_to_px(s.board_width_mm, dpi)
        h = units.mm_to_px(s.height_mm, dpi)
        return imaging.crop_to_board(st.image, w, h, p.zoom, p.pan_x, p.pan_y)

    def net_for(self, book: c.Book) -> net.NetResult:
        st = self.state(book)
        p = self.book_prefs(book)
        return net.build_net(book, st.image, self.settings, p.zoom, p.pan_x, p.pan_y,
                             self.spine_override(book))

    def build_nets(self, progress: Callable[[int, int, str], None] | None = None) -> list[net.NetResult]:
        books = self.selected_books()
        out = []
        for i, b in enumerate(books, 1):
            self.ensure_cover(b)
            out.append(self.net_for(b))
            if progress:
                progress(i, len(books), b.title)
        return out

    def save_suggestion(self) -> tuple[str, str]:
        """(folder, file name) to offer in the save dialog; the folder is the one used last time."""
        return str(self.output_dir), self.default_filename()

    def remember_save_location(self, path: Path | str) -> None:
        self.update_settings(output_dir=str(Path(path).parent))

    def default_filename(self) -> str:
        tag = str(self.year) if self.year else "books"
        return f"minibook_wraps_{tag}.pdf"

    def export(self, progress: Callable[[int, int, str], None] | None = None,
               out_path: Path | None = None) -> tuple[Path, list[net.NetResult], int]:
        """Build everything and write the PDF. Returns (path, nets, pages)."""
        problems = self.settings.validate()
        if problems:
            raise ValueError("; ".join(problems))
        if not self.selected_books():
            raise ValueError("No books are selected.")
        nets = self.build_nets(progress)
        path = Path(out_path) if out_path else self.output_dir / self.default_filename()
        path.parent.mkdir(parents=True, exist_ok=True)
        grid = pdfexport.export_pdf(nets, self.settings, path)
        pages = -(-len(nets) // grid.per_page)
        return path, nets, pages

    def default_svg_filename(self) -> str:
        return self.default_filename()[:-4] + ".svg"

    def export_svg(self, progress: Callable[[int, int, str], None] | None = None,
                   out_path: Path | None = None) -> tuple[list[Path], list[net.NetResult], int]:
        """Build everything and write the pages as SVG files (one per page). Returns (paths, nets, pages)."""
        problems = self.settings.validate()
        if problems:
            raise ValueError("; ".join(problems))
        if not self.selected_books():
            raise ValueError("No books are selected.")
        nets = self.build_nets(progress)
        path = Path(out_path) if out_path else self.output_dir / self.default_svg_filename()
        paths = svgexport.export_svg(nets, self.settings, path)
        return paths, nets, len(paths)

    def export_test_print(self, out_path: Path | None = None) -> tuple[Path, testprint.TestPrintInfo]:
        """The test page: outlines, labelled spines, a ruler and the first ticked book as a full wrap."""
        problems = self.settings.validate()
        if problems:
            raise ValueError("; ".join(problems))
        books = self.selected_books()
        sample = None
        if books:
            self.ensure_cover(books[0])
            sample = self.net_for(books[0])
        path = Path(out_path) if out_path else self.output_dir / "minibook_test_print.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path, testprint.export_test_print(self.settings, sample, path)

    def summary_counts(self) -> dict:
        vis = self.visible()
        return {"shown": len(vis), "selected": sum(b.selected for b in vis),
                "undated": len(self.undated), "pages_estimate": self._pages(sum(b.selected for b in vis))}

    def _pages(self, n: int) -> int:
        from . import layout
        if not n:
            return 0
        try:
            s = self.settings
            g = layout.make_grid(*s.page_mm, s.net_width_mm, s.height_mm, s.gutter_mm, s.margin_mm)
            return layout.page_count(n, g)
        except layout.LayoutError:
            return 0


def pdf_path(path: Path | str) -> Path:
    """Whatever the person typed in the save box, as a path ending in .pdf."""
    p = Path(path).expanduser()
    return p if p.suffix.lower() == ".pdf" else p.with_name(p.name + ".pdf")


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "minibook"

"""Cover lookup on Open Library and Google Books, with a disk cache (IMG-01 .. IMG-04, IMG-07, IMG-10).

All network access goes through an injectable `HttpClient`, so tests use stand-in responses
and the real client is only constructed by the app / CLI.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from difflib import SequenceMatcher
from urllib.parse import urlencode

from PIL import Image, UnidentifiedImageError

from .csvimport import Book, normalize_isbn

USER_AGENT = "MiniBookStudio/1.0 (personal hobby tool)"
MIN_IMAGE_SIDE = 40          # smaller than this is a placeholder, not a cover
MAX_CANDIDATES = 30
PROBE_FIRST = 4              # bulk lookups download only this many promising candidates per book
TIER_GOOD, TIER_MAYBE, TIER_UNLIKELY = 0, 1, 2
TITLE_GOOD, TITLE_PARTIAL = 0.8, 0.55
DEEP_WORKS = 3               # "more options": other editions of this many best-matching works
DEEP_EDITIONS = 12           # ...at most this many editions per work
MAX_IMAGE_BYTES = 15 * 1024 * 1024


class CoverError(Exception):
    pass


# Google Books statuses that mean "stop asking until the key / quota is fixed".
GOOGLE_STOP_HELP = {
    429: "Google Books is limiting requests (HTTP 429). Add a free API key in Settings to use it.",
    403: "Google Books refused the request (HTTP 403). Check the API key and that the Books API is enabled for it.",
    401: "Google Books refused the request (HTTP 401). Check the API key in Settings.",
    400: "Google Books rejected the request (HTTP 400). Check the API key in Settings.",
}


@dataclass
class HttpResponse:
    status: int
    content: bytes


class HttpClient(Protocol):
    def get(self, url: str, params: dict | None = None, timeout: float = 15.0) -> HttpResponse: ...


class RequestsHttp:
    """Real client. Only constructed at runtime; `requests` is imported lazily."""

    def __init__(self):
        import requests
        self._s = requests.Session()
        self._s.headers["User-Agent"] = USER_AGENT

    def get(self, url, params=None, timeout=15.0) -> HttpResponse:
        try:
            r = self._s.get(url, params=params, timeout=timeout)
        except Exception as e:  # network down, DNS, TLS, timeout...
            raise CoverError(f"{type(e).__name__}: {e}") from e
        return HttpResponse(r.status_code, r.content)


@dataclass
class CoverCandidate:
    source: str                 # "Open Library" / "Google Books"
    url: str
    label: str
    note: str = ""
    width: int | None = None    # filled in once the image is downloaded
    height: int | None = None
    title: str = ""             # what the source calls this book (may differ from ours)
    authors: list[str] = field(default_factory=list)
    tier: int = TIER_GOOD       # how likely this is the right book: 0 good, 1 possible, 2 probably not
    why: str = ""               # plain-words reason for tier 1 / 2, shown on the card
    exact: bool = False         # found through the book's own ISBN

    @property
    def size_text(self) -> str:
        return f"{self.width}×{self.height} px" if self.width and self.height else "size unknown"

    @property
    def aspect(self) -> float | None:
        return self.width / self.height if self.width and self.height else None

    @property
    def is_squarish(self) -> bool:
        a = self.aspect
        return a is not None and a > 0.85


@dataclass
class SearchResult:
    candidates: list[CoverCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# -- deciding whether a result is the book we asked for ----------------------------------------------
_BUNDLE = re.compile(
    r"\bbox(?:ed)?[ -]?sets?\b|\bboxset\b|\bomnibus\b|\btrilogy\b|\bquartet\b|\bbundle\b|\bcollection\b"
    r"|\b(?:complete|collected|entire|ultimate)\s+(?:series|saga|novels|works|set)\b"
    r"|\b(?:books?|volumes?|vol\.?|parts?)\s*\d+\s*(?:-|–|—|to|through|&|and)\s*\d+\b"
    r"|\b\d+[- ](?:book|novel|volume)s?\b|\bseries\s+set\b|\bset of \d+\b")
_GUIDE = re.compile(
    r"\bsummary of\b|\bstudy guide\b|\b(?:book )?analysis\b|\bworkbook\b|\bcliffs?\s?notes\b|\bsparknotes\b"
    r"|\btrivia\b|\bunofficial\b|\bcompanion guide\b|\bquiz\b|\bconversation starters\b|\bsupersummary\b")
_GUIDE_CATEGORIES = ("study aids", "literary criticism")


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def clean_title(title: str) -> str:
    """Title without a trailing series note: 'Mistborn: The Final Empire (Mistborn, #1)' -> '... Empire'."""
    t = re.sub(r"\s*\([^)]*\)\s*$", "", title or "").strip()
    return t or (title or "").strip()


def _core(title: str) -> str:
    """Comparable form: no accents or punctuation, no leading article, no series note."""
    t = _plain(clean_title(title))
    return re.sub(r"^(the|a|an) ", "", t)


def _head(title: str) -> str:
    """The part before a subtitle ('The Way of Kings: Book One of ...' -> 'The Way of Kings')."""
    t = clean_title(title)
    return re.split(r"\s*[:\u2013\u2014]\s*|\s+-\s+|,\s+or\s+", t, maxsplit=1)[0]


# Extra words that do not make a different book ('Dune' vs 'Dune Messiah' IS different, so 'messiah' is not here).
_HARMLESS = frozenset(
    "a an the of and or novel book one two three part edition illustrated annotated anniversary deluxe unabridged "
    "abridged new revised classic classics movie tie in special collectors collector hardcover paperback audiobook "
    "audio 1 2 3 i ii iii penguin vintage modern library reissue with introduction".split())


def title_match(wanted: str, found: str) -> float:
    """0..1: how well a result's title matches ours. Subtitles and series notes do not hurt."""
    w, f = _core(wanted), _core(found)
    wh, fh = _core(_head(wanted)), _core(_head(found))
    if not w or not f:
        return 0.0
    best = max(SequenceMatcher(None, a, b).ratio() for a, b in ((w, f), (wh, fh), (wh, f), (w, fh)))
    wt, ft = set(w.split()), set(f.split())
    if wt <= ft and (ft - wt) <= _HARMLESS:     # ours plus words like 'Part One', 'A Novel', 'Illustrated Edition'
        best = max(best, 0.85)
    return best


def _last_names(names: list[str]) -> set[str]:
    out = set()
    for n in names:
        for part in re.split(r"\s*(?:,|&| and )\s*", n or ""):
            words = [w for w in _plain(part).split() if len(w) > 1]
            if words:
                out.add(words[-1])
    return out


def author_match(wanted: list[str], found: list[str]) -> bool | None:
    """True / False, or None when either side does not say who wrote it."""
    a, b = _last_names(wanted), _last_names(found)
    if not a or not b:
        return None
    return bool(a & b)


def bundle_reason(wanted_title: str, found_title: str, categories: list[str] | None = None) -> str:
    """Why a result is probably not the single book (box set, omnibus, study guide...), or ''."""
    ours = _plain(wanted_title)
    text = _plain(found_title)
    for pat, reason in ((_BUNDLE, "looks like a box set or bundle"), (_GUIDE, "looks like a guide or summary")):
        for m in pat.finditer(text):
            if m.group(0) not in ours:               # a book really called 'Trilogy' is fine
                return reason
    cats = " ".join(categories or []).lower()
    if any(c in cats for c in _GUIDE_CATEGORIES) and not any(c in _plain(wanted_title) for c in ("guide", "criticism")):
        return "filed as a guide or reference book"
    return ""


def isbn13_to_10(isbn13: str) -> str | None:
    if not (isbn13 and len(isbn13) == 13 and isbn13.startswith("978") and isbn13.isdigit()):
        return None
    core = isbn13[3:12]
    total = sum((10 - i) * int(ch) for i, ch in enumerate(core))
    check = (11 - total % 11) % 11
    return core + ("X" if check == 10 else str(check))


def likely(cands: list[CoverCandidate]) -> list[CoverCandidate]:
    """What the picker shows: the good matches; the merely possible ones only when there is no good one.
    Box sets, guides and other titles are never shown, so they are never even downloaded."""
    good = [c for c in cands if c.tier == TIER_GOOD]
    return good or [c for c in cands if c.tier == TIER_MAYBE]


def grade(book: Book, cand: CoverCandidate, categories: list[str] | None = None) -> None:
    """Fill in `tier` and `why` for a candidate that came with a title (and maybe authors)."""
    if not cand.title:
        return                                           # nothing to compare (an ISBN cover): trusted as is
    reason = bundle_reason(book.title, cand.title, categories)
    if reason:
        cand.tier, cand.why = TIER_UNLIKELY, reason
        return
    if cand.exact:
        return
    t = title_match(book.title, cand.title)
    a = author_match(book.authors, cand.authors)
    if t >= TITLE_GOOD:
        if a is False:
            cand.tier, cand.why = TIER_MAYBE, "different author listed"
    elif t >= TITLE_PARTIAL:
        cand.tier, cand.why = TIER_MAYBE, "title only partly matches"
        if a is False:
            cand.tier, cand.why = TIER_UNLIKELY, "different title and author"
    else:
        cand.tier, cand.why = TIER_UNLIKELY, "a different title"


class CoverService:
    def __init__(self, http: HttpClient, cache_dir: Path, google_api_key: str | None = None,
                 max_workers: int = 4):
        self.http = http
        self.cache_dir = Path(cache_dir)
        self.google_api_key = google_api_key
        self.max_workers = max_workers
        self.network_calls = 0       # lets tests prove the cache works (IMG-02)
        self._lock = threading.Lock()
        self.google_blocked = False      # circuit breaker: stop hammering Google after a 429 etc.
        self.notices: list[str] = []     # session-level messages for the UI (shown once)

    # -- cached HTTP -------------------------------------------------------------
    def _cached_get(self, url: str, params: dict | None, kind: str) -> bytes:
        full = url + ("?" + urlencode(sorted((params or {}).items())) if params else "")
        path = self.cache_dir / kind / (_key(full) + (".json" if kind == "search" else ".img"))
        miss = path.with_suffix(".miss")
        if path.exists():
            return path.read_bytes()
        if miss.exists():                      # a cached 404: this ISBN/URL has no cover
            raise CoverError("HTTP 404")
        with self._lock:
            self.network_calls += 1
        resp = self.http.get(url, params=params)
        if resp.status == 404:
            _atomic_write_bytes(miss, b"")
        if resp.status != 200:
            raise CoverError(f"HTTP {resp.status}")
        if len(resp.content) > MAX_IMAGE_BYTES:
            raise CoverError("response too large")
        _atomic_write_bytes(path, resp.content)
        return resp.content

    def _search_json(self, url: str, params: dict) -> dict:
        data = self._cached_get(url, params, "search")
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError as e:
            raise CoverError("unreadable search response") from e

    def set_google_key(self, key: str | None) -> None:
        """Change the key and give Google another chance (a new key may fix a 429)."""
        key = (key or "").strip() or None
        if key != self.google_api_key:
            self.google_api_key = key
            self.google_blocked = False
            self.notices = [n for n in self.notices if not n.startswith("Google Books")]

    # -- providers -----------------------------------------------------------------
    def _open_library_isbn(self, isbn: str, note: str = "") -> list[CoverCandidate]:
        return [CoverCandidate("Open Library", f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false",
                               f"ISBN {isbn}", note, exact=True)]

    def _amazon_ids(self, book: Book) -> list[str]:
        ids = []
        if book.isbn and (i10 := isbn13_to_10(book.isbn)):
            ids.append(i10)
        if book.asin:
            ids.append(book.asin)
        return ids

    def _amazon(self, book: Book, note: str = "") -> list[CoverCandidate]:
        """Amazon's picture for the book's ISBN-10 / ASIN. Often the largest one there is. A missing
        picture comes back as a 1-pixel image, which is dropped later like any placeholder."""
        return [CoverCandidate("Amazon", f"https://images-na.ssl-images-amazon.com/images/P/{i}.01.LZZZZZZZ.jpg",
                               f"{'ASIN' if i.startswith('B0') else 'ISBN-10'} {i}", note, exact=True)
                for i in self._amazon_ids(book)]

    def _open_library_search(self, book: Book, deep: bool = False) -> list[CoverCandidate]:
        title = clean_title(book.title)
        params = {"title": title, "limit": 10,
                  "fields": "key,title,author_name,cover_i,first_publish_year"}
        if book.authors:
            params["author"] = book.authors[0]
        data = self._search_json("https://openlibrary.org/search.json", params)
        docs = data.get("docs", []) or []
        out = []
        for doc in docs:
            cid = doc.get("cover_i")
            if not cid:
                continue
            year = doc.get("first_publish_year")
            found = doc.get("title", book.title)
            cand = CoverCandidate("Open Library", f"https://covers.openlibrary.org/b/id/{cid}-L.jpg?default=false",
                                  found + (f" ({year})" if year else ""), title=found,
                                  authors=list(doc.get("author_name") or []))
            grade(book, cand)
            out.append(cand)
        if deep:
            matching = [d for d in docs if d.get("key") and title_match(book.title, d.get("title", "")) >= TITLE_GOOD
                        and author_match(book.authors, list(d.get("author_name") or [])) is not False]
            for doc in matching[:DEEP_WORKS]:
                out.extend(self._open_library_editions(book, doc))
        return out

    def _open_library_editions(self, book: Book, doc: dict) -> list[CoverCandidate]:
        """Other editions of a work that matched: different printings often have different covers."""
        try:
            data = self._search_json(f"https://openlibrary.org{doc['key']}/editions.json", {"limit": 40})
        except CoverError:
            return []
        out = []
        for ed in data.get("entries", []) or []:
            ids = [i for i in (ed.get("covers") or []) if isinstance(i, int) and i > 0]
            if not ids:
                continue
            found = ed.get("title") or doc.get("title", book.title)
            when = ed.get("publish_date") or ""
            fmt = ed.get("physical_format") or ""
            label = f"{found} — " + ", ".join(x for x in (fmt, when) if x) if (fmt or when) else found
            cand = CoverCandidate("Open Library", f"https://covers.openlibrary.org/b/id/{ids[0]}-L.jpg?default=false",
                                  label, title=found, authors=list(doc.get("author_name") or []))
            grade(book, cand)
            out.append(cand)
            if len(out) >= DEEP_EDITIONS:
                break
        return out

    def _google(self, q: str, label_prefix: str, note: str = "", book: Book | None = None,
                exact: bool = False, max_results: int = 8) -> list[CoverCandidate]:
        if self.google_blocked:
            return []                     # already reported once this session
        params = {"q": q, "maxResults": max_results, "printType": "books"}
        if self.google_api_key:
            params["key"] = self.google_api_key
        try:
            data = self._search_json("https://www.googleapis.com/books/v1/volumes", params)
        except CoverError as e:
            status = int(m.group(1)) if (m := re.fullmatch(r"HTTP (\d{3})", str(e))) else None
            if status in GOOGLE_STOP_HELP:
                self.google_blocked = True
                help_text = GOOGLE_STOP_HELP[status]
                if help_text not in self.notices:
                    self.notices.append(help_text)
                raise CoverError(help_text) from e
            raise
        out = []
        for item in data.get("items", []) or []:
            info = item.get("volumeInfo", {}) or {}
            links = info.get("imageLinks", {}) or {}
            url = next((links[k] for k in ("extraLarge", "large", "medium", "small", "thumbnail")
                        if links.get(k)), None)
            if not url:
                continue
            url = url.replace("http://", "https://").replace("&edge=curl", "")
            date = (info.get("publishedDate") or "")[:4]
            found = ": ".join(x for x in (info.get("title", ""), info.get("subtitle", "")) if x)
            label = f"{label_prefix}: {info.get('title', '')}" + (f" ({date})" if date else "")
            cand = CoverCandidate("Google Books", url, label, note, title=found,
                                  authors=list(info.get("authors") or []), exact=exact)
            if book is not None:
                grade(book, cand, list(info.get("categories") or []))
            out.append(cand)
        return out

    # -- public API -------------------------------------------------------------------
    def search(self, book: Book, deep: bool = False) -> SearchResult:
        """Gather candidate covers (IMG-01, IMG-03). Network errors become messages, not crashes (IMG-10).

        Every result is graded (good / possible / probably not) and the list is ordered by that grade, so
        the likely covers come first and box sets, guides and other titles sit at the end, still available.
        `deep` also pulls other editions of the matching work from Open Library.
        """
        result = SearchResult()
        by_isbn: list[CoverCandidate] = []
        by_title: list[CoverCandidate] = []
        audio_note = "may be audiobook art" if book.is_audio else ""

        def attempt(name: str, fn):
            try:
                return fn()
            except CoverError as e:
                result.errors.append(f"{name}: {e}")
            except Exception as e:  # never let one source stop the run
                result.errors.append(f"{name}: {type(e).__name__}: {e}")
            return []

        title = clean_title(book.title)
        last = next(iter(sorted(_last_names(book.authors))), "") if book.authors else ""
        q = f'intitle:"{title}"' + (f' inauthor:"{last}"' if last else "") if title else ""
        # The lookups are independent, so they run side by side instead of one after another.
        jobs: list[tuple[str, object]] = []
        if book.isbn:
            jobs.append(("isbn", lambda: self._open_library_isbn(book.isbn, audio_note)))
            jobs.append(("isbn", lambda: attempt("Google Books (ISBN)", lambda: self._google(
                f"isbn:{book.isbn}", "ISBN match", audio_note, book, exact=True))))
        jobs.append(("isbn", lambda: self._amazon(book, audio_note)))
        if title:
            jobs.append(("title", lambda: attempt("Open Library (title)", lambda: self._open_library_search(book, deep))))
            jobs.append(("title", lambda: attempt("Google Books (title)", lambda: self._google(
                q, "Title search", book=book))))
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [(group, pool.submit(fn)) for group, fn in jobs]
            for group, fut in futures:                       # collected in order, so results stay deterministic
                (by_isbn if group == "isbn" else by_title).extend(fut.result())

        ordered = (by_title + by_isbn) if book.is_audio else (by_isbn + by_title)  # IMG-03
        seen: set[str] = set()
        unique = []
        for c in ordered:
            if c.url not in seen:
                seen.add(c.url)
                unique.append(c)
        unique.sort(key=lambda c: c.tier)                    # stable: the order above holds within a grade
        result.candidates = unique[: MAX_CANDIDATES * 2]
        return result

    def load_image(self, cand: CoverCandidate) -> Image.Image:
        """Download (or read from cache) and decode a candidate; records its pixel size (IMG-04)."""
        data = self._cached_get(cand.url, None, "img")
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except (UnidentifiedImageError, OSError) as e:
            raise CoverError("not a readable image") from e
        if min(img.size) < MIN_IMAGE_SIDE:
            raise CoverError("placeholder image")
        cand.width, cand.height = img.size
        return img.convert("RGB")

    def _digest(self, cand: CoverCandidate) -> str | None:
        """Download one candidate (sets its size); a fingerprint of the picture, or None if unusable."""
        try:
            img = self.load_image(cand)
        except CoverError:
            return None
        return hashlib.sha1(img.tobytes()[:200000]).hexdigest() + f"{img.size}"

    def probe(self, cands: list[CoverCandidate]) -> list[CoverCandidate]:
        """Download every candidate; keep the usable ones, once per distinct picture, in the given order."""
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            digests = list(pool.map(self._digest, cands))
        usable, seen = [], set()
        for cand, digest in zip(cands, digests):
            if digest is None or digest in seen:
                continue
            seen.add(digest)
            usable.append(cand)
        return usable

    def find_covers(self, book: Book, probe: str = "all", deep: bool = False, likely_only: bool = False) -> SearchResult:
        """Search, then download candidates to learn their sizes; unusable ones are dropped.

        probe="all" downloads every candidate (the cover picker). probe="some" downloads only the first
        few promising ones (grade 0 or 1) and leaves the rest listed but not yet downloaded: that is all
        a bulk run needs to choose a cover, and it keeps fetching 50 books quick.
        Candidates with identical pixels (same cover from two sources) are collapsed.
        """
        res = self.search(book, deep)
        if likely_only:
            res.candidates = likely(res.candidates)
        if probe == "all":
            res.candidates = self.probe(res.candidates)[:MAX_CANDIDATES]
        else:
            front = [c for c in res.candidates if c.tier <= TIER_MAYBE][:PROBE_FIRST + 2]
            kept = self.probe(front)
            dead = {id(c) for c in front} - {id(c) for c in kept}
            res.candidates = [c for c in res.candidates if id(c) not in dead][:MAX_CANDIDATES]
        if not res.candidates and not res.errors:
            res.errors.append("no cover found")
        return res


def load_local_image(path) -> Image.Image:
    """Custom upload (IMG-07). Accepts a file path or a file-like object."""
    try:
        img = Image.open(path)
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise CoverError(f"could not open image: {e}") from e
    if min(img.size) < MIN_IMAGE_SIDE:
        raise CoverError("image is too small to use as a cover")
    return img.convert("RGB")

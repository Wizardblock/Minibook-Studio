"""StoryGraph and Goodreads CSV import, filtering and sorting (DATA-01 .. DATA-09, DATA-11, DATA-12)."""
from __future__ import annotations

import csv
import hashlib
import html
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

ALL_STATUSES = "*"          # filter_books: every status, including books with none
REQUIRED_COLUMNS = ["Title", "Authors"]
KNOWN_COLUMNS = ["Title", "Authors", "ISBN/UID", "Format", "Read Status",
                 "Last Date Read", "Dates Read", "Star Rating", "Review"]


@dataclass(frozen=True)
class ReadDate:
    year: int
    month: int | None = None
    day: int | None = None

    def sort_key(self) -> tuple[int, int, int]:
        return (self.year, self.month or 0, self.day or 0)

    def __str__(self) -> str:
        if self.day:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        if self.month:
            return f"{self.year:04d}-{self.month:02d}"
        return f"{self.year:04d}"


@dataclass
class Book:
    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None            # normalized ISBN-13 (DATA-08)
    asin: str | None = None            # Amazon ID such as B00351YF0C (not usable for cover APIs)
    format: str = ""                   # hardcover / paperback / audio / digital / ""
    status: str = ""                   # read / to-read / currently-reading / ""
    read_date: ReadDate | None = None
    rating: float | None = None
    review: str = ""
    selected: bool = True
    source: str = "csv"                # "csv" or "manual"
    duplicate: bool = False            # DATA-09
    source_id: str = ""                # id when first created; stays put when the book is edited

    def __post_init__(self):
        if not self.source_id:
            self.source_id = self.id

    @property
    def author(self) -> str:
        return ", ".join(self.authors)

    @property
    def year(self) -> int | None:
        return self.read_date.year if self.read_date else None

    @property
    def is_audio(self) -> bool:
        return self.format.lower() == "audio"

    @property
    def id(self) -> str:
        """Stable key for remembering per-book choices (SET-03)."""
        basis = self.isbn or self.asin or f"{self.title.lower()}|{self.author.lower()}"
        return hashlib.sha1(f"{basis}|{self.format.lower()}".encode("utf-8")).hexdigest()[:16]


UNCHANGED = object()       # apply_edit: leave this field as it is


def parse_user_date(text: str) -> ReadDate | None:
    """DATA-12: a date typed by hand: 2024, 2024-05 or 2024-05-17 (also with / or .). Blank = no date."""
    t = (text or "").strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?", t)
    if not m:
        raise ValueError("Date read must look like 2024, 2024-05 or 2024-05-17")
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else None
    day = int(m.group(3)) if m.group(3) else None
    if not 1900 <= year <= 2200:
        raise ValueError("Date read: the year must be between 1900 and 2200")
    if month is not None and not 1 <= month <= 12:
        raise ValueError("Date read: the month must be 1 to 12")
    if day is not None:
        import calendar
        if not 1 <= day <= calendar.monthrange(year, month)[1]:
            raise ValueError("Date read: that day does not exist in that month")
    return ReadDate(year, month, day)


def parse_user_rating(value) -> float | None:
    """DATA-12: a star rating typed or picked by hand: 0.25 to 5 in quarter steps. Blank or 0 = none."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        r = float(value)
    except (TypeError, ValueError):
        raise ValueError("Star rating must be a number from 0 to 5") from None
    if r == 0:
        return None
    if not 0 < r <= 5:
        raise ValueError("Star rating must be between 0 and 5")
    return round(r * 4) / 4


def apply_edit(book: Book, title: str, author: str, isbn: str,
               read_date=UNCHANGED, rating=UNCHANGED) -> None:
    """DATA-10/12: change a book's title, author, ISBN, date read or rating in place.
    Raises ValueError on bad input, and then changes nothing."""
    new_date = book.read_date if read_date is UNCHANGED else (
        read_date if isinstance(read_date, ReadDate) or read_date is None else parse_user_date(read_date))
    new_rating = book.rating if rating is UNCHANGED else parse_user_rating(rating)
    title = (title or "").strip()
    if not title:
        raise ValueError("A title is required")
    raw = (isbn or "").strip()
    i13, asin = normalize_isbn(raw)
    if raw and not (i13 or asin):
        raise ValueError("That is not a valid ISBN-10, ISBN-13 or Amazon ASIN")
    book.title, book.authors, book.isbn, book.asin = title, split_authors(author), i13, asin
    book.read_date, book.rating = new_date, new_rating


# -- cleaning -------------------------------------------------------------------
def isbn10_valid(s: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dXx]", s):
        return False
    total = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(s))
    return total % 11 == 0


def isbn13_valid(s: str) -> bool:
    if not re.fullmatch(r"\d{13}", s):
        return False
    return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s)) % 10 == 0


def isbn10_to_13(s: str) -> str:
    core = "978" + s[:9]
    check = (10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core)) % 10) % 10
    return core + str(check)


def normalize_isbn(raw: str) -> tuple[str | None, str | None]:
    """Return (isbn13, asin). Either or both may be None."""
    s = (raw or "").strip().replace("-", "").replace(" ", "")
    if not s:
        return None, None
    if isbn13_valid(s):
        return s, None
    if isbn10_valid(s):
        return isbn10_to_13(s.upper()), None
    if re.fullmatch(r"B0[0-9A-Z]{8}", s.upper()):
        return None, s.upper()
    return None, None


def clean_review(raw: str) -> str:
    text = re.sub(r"<\s*br\s*/?>", "\n", raw or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def split_authors(raw: str) -> list[str]:
    return [a.strip() for a in (raw or "").split(",") if a.strip()]


_DATE_TOKEN = re.compile(r"(\d{4})(?:/(\d{1,2}))?(?:/(\d{1,2}))?")


def _parse_date_token(token: str) -> ReadDate | None:
    m = _DATE_TOKEN.search(token or "")
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else None
    day = int(m.group(3)) if m.group(3) else None
    if not 1900 <= year <= 2200:
        return None
    if month is not None and not 1 <= month <= 12:
        month, day = None, None
    if day is not None and not 1 <= day <= 31:
        day = None
    return ReadDate(year, month, day)


def parse_read_date(last_date_read: str, dates_read: str) -> ReadDate | None:
    """DATA-03: Last Date Read first, else the end of Dates Read ('2024-' counts as 2024)."""
    d = _parse_date_token((last_date_read or "").strip())
    if d:
        return d
    tokens = _DATE_TOKEN.findall(dates_read or "")
    if not tokens:
        return None
    # the last token in a range is the end of the range
    y, m, dd = tokens[-1]
    return _parse_date_token("/".join(p for p in (y, m, dd) if p))


def parse_rating(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if 0 < v <= 5 else None


# -- parsing --------------------------------------------------------------------
class CsvFormatError(ValueError):
    pass


def parse_storygraph(source: str | bytes | Path | io.TextIOBase) -> list[Book]:
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8-sig")
    elif isinstance(source, bytes):
        text = source.decode("utf-8-sig")
    elif isinstance(source, str):
        text = source.lstrip("﻿")
    else:
        text = source.read().lstrip("﻿")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = reader.fieldnames or []
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise CsvFormatError(
            "This does not look like a StoryGraph export. Missing column(s): " + ", ".join(missing))

    books: list[Book] = []
    for row in reader:
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        isbn, asin = normalize_isbn(row.get("ISBN/UID", ""))
        books.append(Book(
            title=title,
            authors=split_authors(row.get("Authors", "")),
            isbn=isbn,
            asin=asin,
            format=(row.get("Format") or "").strip().lower(),
            status=(row.get("Read Status") or "").strip().lower(),
            read_date=parse_read_date(row.get("Last Date Read", ""), row.get("Dates Read", "")),
            rating=parse_rating(row.get("Star Rating", "")),
            review=clean_review(row.get("Review", "")),
            source="csv",
        ))
    return books


# -- Goodreads ------------------------------------------------------------------
GOODREADS_COLUMNS = ["Book Id", "Title", "Author", "Exclusive Shelf"]
_SERIES_TAIL = re.compile(r"\s*\([^()]*#\s*\d+[^()]*\)\s*$")


def _excel_text(raw: str) -> str:
    """Goodreads writes ISBNs as ="0804139024" so spreadsheets keep the zeros; undo that."""
    t = (raw or "").strip()
    m = re.fullmatch(r'=?"*([^"]*)"*', t)
    return (m.group(1) if m else t).strip()


def clean_goodreads_title(title: str) -> str:
    """'The Martian (Series, #1)' -> 'The Martian'. Only a trailing bracket that holds a '#number'."""
    cleaned = _SERIES_TAIL.sub("", title or "").strip()
    return cleaned or (title or "").strip()


def goodreads_format(binding: str) -> str:
    b = (binding or "").lower()
    if "audio" in b:
        return "audio"
    if "kindle" in b or "ebook" in b or "e-book" in b or "digital" in b:
        return "digital"
    if "hardcover" in b or "hardback" in b:
        return "hardcover"
    if "paperback" in b or "binding" in b:
        return "paperback"
    return ""


def is_goodreads(columns) -> bool:
    return all(c in (columns or []) for c in GOODREADS_COLUMNS)


def _read_text(source) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8-sig")
    if isinstance(source, bytes):
        return source.decode("utf-8-sig")
    if isinstance(source, str):
        return source.lstrip("\ufeff")
    return source.read().lstrip("\ufeff")


def parse_goodreads(source) -> list[Book]:
    """DATA-11: a Goodreads library export."""
    reader = csv.DictReader(io.StringIO(_read_text(source), newline=""))
    missing = [c for c in GOODREADS_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise CsvFormatError("This does not look like a Goodreads export. Missing column(s): " + ", ".join(missing))
    books: list[Book] = []
    for row in reader:
        title = clean_goodreads_title(row.get("Title") or "")
        if not title:
            continue
        isbn, asin = normalize_isbn(_excel_text(row.get("ISBN13", "")))
        if not (isbn or asin):
            isbn, asin = normalize_isbn(_excel_text(row.get("ISBN", "")))
        authors = split_authors(row.get("Author", "")) + split_authors(row.get("Additional Authors", ""))
        books.append(Book(
            title=title,
            authors=list(dict.fromkeys(authors)),
            isbn=isbn,
            asin=asin,
            format=goodreads_format(row.get("Binding", "")),
            status=(row.get("Exclusive Shelf") or "").strip().lower(),
            read_date=_parse_date_token(row.get("Date Read", "")),
            rating=parse_rating(row.get("My Rating", "")),      # Goodreads uses 0 for "not rated"
            review=clean_review(row.get("My Review", "")),
            source="csv",
        ))
    return books


def parse_library_csv(source) -> list[Book]:
    """DATA-01/11: a StoryGraph or a Goodreads export, told apart by its columns."""
    text = _read_text(source)
    cols = csv.DictReader(io.StringIO(text, newline="")).fieldnames or []
    if is_goodreads(cols):
        return parse_goodreads(text)
    if all(c in cols for c in REQUIRED_COLUMNS):
        return parse_storygraph(text)
    raise CsvFormatError("This does not look like a StoryGraph or Goodreads export. "
                         "Expected columns such as Title and Authors (StoryGraph) or Title, Author and "
                         "Exclusive Shelf (Goodreads).")


def manual_book(title: str, author: str = "", isbn: str = "", format: str = "",
                read_date: str = "", rating=None) -> Book:
    """DATA-06, DATA-12 (date read and star rating can be typed in)."""
    title = (title or "").strip()
    if not title:
        raise ValueError("A title is required")
    i13, asin = normalize_isbn(isbn)
    return Book(title=title, authors=split_authors(author), isbn=i13, asin=asin,
                format=format.lower(), status="read", source="manual",
                read_date=parse_user_date(read_date), rating=parse_user_rating(rating))


# -- filtering / selection / sorting ---------------------------------------------
def available_years(books: list[Book]) -> list[int]:
    return sorted({b.year for b in books if b.year}, reverse=True)


def filter_books(books: list[Book], statuses: set[str] | None = None,
                 year: int | None = None) -> tuple[list[Book], list[Book]]:
    """DATA-02/04. Returns (dated_matches, undated).

    `statuses` defaults to {'read'}; {'*'} means every status (including blank). With a year, dated books must match it; undated books
    (no usable read date) are returned separately so they never vanish silently.
    """
    statuses = statuses or {"read"}
    pool = list(books) if ALL_STATUSES in statuses else [b for b in books if b.status in statuses]
    undated = [b for b in pool if b.read_date is None]
    dated = [b for b in pool if b.read_date is not None]
    if year is not None:
        dated = [b for b in dated if b.year == year]
    return dated, undated


def apply_default_selection(dated: list[Book], undated: list[Book]) -> None:
    """DATA-04/05: dated matches checked, undated unchecked."""
    for b in dated:
        b.selected = True
    for b in undated:
        b.selected = False


def _last_name_key(authors: list[str]) -> str:
    if not authors:
        return ""
    first = authors[0].strip()
    parts = first.split()
    return (parts[-1] if parts else first).lower()


def sort_books(books: list[Book], how: str = "author") -> list[Book]:
    """DATA-07: author (last name) -> date read -> title; or by title; or by date."""
    far = (9999, 99, 99)
    if how == "title":
        return sorted(books, key=lambda b: b.title.lower())
    if how == "date":
        return sorted(books, key=lambda b: (b.read_date.sort_key() if b.read_date else far, b.title.lower()))
    return sorted(books, key=lambda b: (_last_name_key(b.authors), b.author.lower(),
                                        b.read_date.sort_key() if b.read_date else far,
                                        b.title.lower()))


def flag_duplicates(books: list[Book]) -> list[str]:
    """DATA-09: mark books sharing a normalized title. Returns the duplicated titles."""
    def norm(t: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()

    seen: dict[str, list[Book]] = {}
    for b in books:
        seen.setdefault(norm(b.title), []).append(b)
    dups = []
    for key, group in seen.items():
        flag = len(group) > 1
        for b in group:
            b.duplicate = flag
        if flag:
            dups.append(group[0].title)
    return dups

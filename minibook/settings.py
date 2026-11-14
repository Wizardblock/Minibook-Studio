"""Saved settings and per-book choices (SET-01, SET-02, SET-03, DIM-01..03)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from . import units

APP_NAME = "MiniBookStudio"
SETTINGS_VERSION = 1

# Default board: 1.25 in tall x 0.75 in wide with a 0.25 in spine (assumption A1, revised).
DEFAULT_HEIGHT_MM = units.in_to_mm(1.25)
DEFAULT_WIDTH_MM = units.in_to_mm(0.75)
DEFAULT_THICKNESS_MM = units.in_to_mm(0.25)

PAPERS_MM = {"letter": (215.9, 279.4), "a4": (210.0, 297.0)}

MIN_GUTTER_MM = 3.0  # EXP-02
MARK_OFFSET_MM = 0.5  # gap between the net corner and the start of a cut mark
MARK_MAX_LEN_MM = 3.0
MARK_GAP_MM = 0.5     # clear space between the marks of two neighbouring nets
FOLD_MARK_RATIO = 0.6  # fold marks are this fraction of the cut-mark length


def mark_length_mm(gutter_mm: float) -> float:
    """Longest cut mark that cannot touch the neighbouring net's mark (EXP-02, EXP-03)."""
    return max(0.0, min(MARK_MAX_LEN_MM, (gutter_mm - 2 * MARK_OFFSET_MM - MARK_GAP_MM) / 2))


def fold_mark_length_mm(gutter_mm: float) -> float:
    """Fold marks are shorter than cut marks so the two cannot be confused (EXP-03b)."""
    return mark_length_mm(gutter_mm) * FOLD_MARK_RATIO


def config_dir() -> Path:
    try:
        from platformdirs import user_config_dir
        return Path(user_config_dir(APP_NAME, appauthor=False))
    except Exception:  # platformdirs missing: fall back to a home dotfolder
        return Path.home() / f".{APP_NAME.lower()}"


def cache_dir() -> Path:
    try:
        from platformdirs import user_cache_dir
        return Path(user_cache_dir(APP_NAME, appauthor=False))
    except Exception:
        return Path.home() / f".{APP_NAME.lower()}" / "cache"


@dataclass
class Settings:
    version: int = SETTINGS_VERSION
    unit: str = "in"                    # display unit: "in", "mm" or "px" (px = pixels at `dpi`)
    size_mode: str = "width"            # "width" = height + width, "aspect" = height + aspect ratio
    height_mm: float = DEFAULT_HEIGHT_MM
    width_mm: float = DEFAULT_WIDTH_MM
    aspect: float = DEFAULT_WIDTH_MM / DEFAULT_HEIGHT_MM
    thickness_mm: float = DEFAULT_THICKNESS_MM
    dpi: int = 300
    back_style: str = "copy"            # "copy", "complement" or "details" (complement + date / stars)
    back_show_date: bool = True         # "details" only
    back_show_rating: bool = True       # "details" only
    back_date_format: str = "full"      # "full" (Mar 5, 2026), "month" (Mar 2026) or "year" (2026)
    spine_hide_author: bool = False
    spine_drop_subtitle: bool = False
    spine_min_font_pt: float = 4.0
    spine_max_font_pt: float = 12.0     # upper limit; the spine's own width may force it lower
    spine_wrap: bool = False            # wrap a too-long title onto two lines instead of truncating
    fold_marks: bool = True             # short marks where the spine meets each cover
    spine_reverse: bool = False         # False = text reads top to bottom
    paper: str = "letter"
    gutter_mm: float = 5.0
    margin_mm: float = 8.0
    sort: str = "author"
    google_api_key: str = ""            # optional free key; avoids Google Books rate limits
    output_dir: str = ""                # where PDFs are saved; "" = Documents (or home)

    # -- derived board geometry -------------------------------------------------
    @property
    def board_width_mm(self) -> float:
        if self.size_mode == "aspect":
            return self.height_mm * self.aspect
        return self.width_mm

    @property
    def net_width_mm(self) -> float:
        return 2 * self.board_width_mm + self.thickness_mm

    @property
    def page_mm(self) -> tuple[float, float]:
        return PAPERS_MM[self.paper]

    def min_margin_mm(self) -> float:
        """Smallest page margin that keeps every cut mark on the page (EXP-06)."""
        return MARK_OFFSET_MM + mark_length_mm(self.gutter_mm)

    def validate(self) -> list[str]:
        """Return human-readable problems (empty list = OK)."""
        problems = []
        if self.unit not in units.UNITS:
            problems.append("unit must be 'in', 'mm' or 'px'")
        if self.size_mode not in ("width", "aspect"):
            problems.append("size_mode must be 'width' or 'aspect'")
        if self.back_style not in ("copy", "complement", "details"):
            problems.append("back_style must be 'copy', 'complement' or 'details'")
        if self.back_date_format not in ("full", "month", "year"):
            problems.append("back_date_format must be 'full', 'month' or 'year'")
        if self.paper not in PAPERS_MM:
            problems.append("paper must be 'letter' or 'a4'")
        for name in ("height_mm", "thickness_mm"):
            if not getattr(self, name) > 0:
                problems.append(f"{name} must be positive")
        if self.size_mode == "width" and not self.width_mm > 0:
            problems.append("width_mm must be positive")
        if self.size_mode == "aspect" and not (0.1 <= self.aspect <= 10):
            problems.append("aspect ratio out of range")
        if not self.spine_min_font_pt > 0:
            problems.append("smallest text size must be positive")
        if self.spine_max_font_pt < self.spine_min_font_pt:
            problems.append("largest text size must not be smaller than the smallest")
        if not 72 <= self.dpi <= 1200:
            problems.append("dpi must be between 72 and 1200")
        if self.gutter_mm < MIN_GUTTER_MM:
            problems.append(f"gutter must be at least {MIN_GUTTER_MM} mm so cut marks do not collide")
        if self.margin_mm < self.min_margin_mm():
            problems.append("page margin is too small for the cut marks")
        pw, ph = PAPERS_MM.get(self.paper, PAPERS_MM["letter"])
        if self.net_width_mm + 2 * self.margin_mm > pw or self.height_mm + 2 * self.margin_mm > ph:
            problems.append("one book does not fit on the page with this margin")
        return problems


def _coerce(default, value):
    """Coerce a loaded JSON value to the type of the default, or raise."""
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        return int(value)
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError
        return value
    return value


def settings_from_dict(data: dict) -> Settings:
    base = Settings()
    if not isinstance(data, dict):
        return base
    for f in fields(Settings):
        if f.name == "version" or f.name not in data:
            continue
        try:
            setattr(base, f.name, _coerce(getattr(base, f.name), data[f.name]))
        except (ValueError, TypeError):
            continue  # keep the default for a bad field
    if base.validate():
        # A saved combination that cannot print is replaced wholesale rather than half-trusted.
        return Settings()
    return base


def load_settings(path: Path | None = None) -> Settings:
    path = path or (config_dir() / "settings.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return Settings()
    return settings_from_dict(data)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    path = path or (config_dir() / "settings.json")
    _atomic_write(path, json.dumps(asdict(settings), indent=2))
    return path


# -- export / import of output settings (SET-04) ---------------------------------------
SETTINGS_FILE_FORMAT = "minibook-settings"
# Machine- or person-specific values never travel in a settings file.
NOT_EXPORTED = ("version", "google_api_key", "output_dir")
DEFAULT_SETTINGS_FILENAME = "minibook-settings.json"


@dataclass
class ImportResult:
    settings: "Settings | None"          # None when nothing could be applied
    applied: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)     # unknown or unusable entries, by name
    problems: list[str] = field(default_factory=list)    # why the file was refused, if it was


def export_settings_text(settings: Settings) -> str:
    """The shareable settings file: output settings only, no Google key, folders or per-book data."""
    body = {k: v for k, v in asdict(settings).items() if k not in NOT_EXPORTED}
    return json.dumps({"format": SETTINGS_FILE_FORMAT, "version": SETTINGS_VERSION, "settings": body}, indent=2)


def import_settings_text(text: str | bytes, current: Settings) -> ImportResult:
    """Read a settings file on top of `current`. Valid entries are applied and the rest are listed.

    The Google key and save folder always stay as they are. A file whose settings cannot print
    together (for example boards too big for the paper) is refused whole, with the reasons.
    """
    try:
        raw = json.loads(text.decode("utf-8-sig") if isinstance(text, bytes) else text)
    except (ValueError, UnicodeDecodeError):
        return ImportResult(None, problems=["That file is not a settings file (it is not valid JSON)."])
    if not isinstance(raw, dict) or raw.get("format") != SETTINGS_FILE_FORMAT \
            or not isinstance(raw.get("settings"), dict):
        return ImportResult(None, problems=["That file is not a MiniBook Studio settings file."])
    if isinstance(raw.get("version"), int) and raw["version"] > SETTINGS_VERSION:
        return ImportResult(None, problems=["That settings file comes from a newer version of the app."])
    incoming = raw["settings"]
    merged = replace(current)
    result = ImportResult(None)
    known = {f.name for f in fields(Settings)} - set(NOT_EXPORTED)
    for name, value in incoming.items():
        if name not in known:
            result.ignored.append(f"{name} (not a setting this version knows)")
            continue
        try:
            setattr(merged, name, _coerce(getattr(current, name), value))
            result.applied.append(name)
        except (ValueError, TypeError):
            result.ignored.append(f"{name} (wrong kind of value)")
    problems = merged.validate()
    if problems:
        result.problems = problems
        result.applied = []
        return result
    result.settings = merged
    return result


# -- per-book choices (SET-03) ----------------------------------------------------
@dataclass
class BookPrefs:
    cover_url: str | None = None        # chosen candidate URL
    custom_path: str | None = None      # a user-supplied image file; in use when no online cover is chosen
    spine_color: str | None = None      # "#rrggbb" chosen for the spine and solid back; None = automatic
    spine_cover: str | None = None      # fingerprint of the cover the color was chosen for; used only with that cover
    zoom: float = 1.0
    pan_x: float = 0.5
    pan_y: float = 0.5


def load_book_prefs(path: Path | None = None) -> dict[str, BookPrefs]:
    path = path or (config_dir() / "book_prefs.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    out: dict[str, BookPrefs] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        p = BookPrefs()
        for f in fields(BookPrefs):
            if f.name in val:
                try:
                    cur = getattr(p, f.name)
                    v = val[f.name]
                    if cur is None:
                        if v is not None and not isinstance(v, str):
                            continue
                        setattr(p, f.name, v)
                    else:
                        setattr(p, f.name, _coerce(cur, v))
                except (ValueError, TypeError):
                    pass
        out[str(key)] = p
    return out


def save_book_prefs(prefs: dict[str, BookPrefs], path: Path | None = None) -> Path:
    path = path or (config_dir() / "book_prefs.json")
    _atomic_write(path, json.dumps({k: asdict(v) for k, v in prefs.items()}, indent=2))
    return path

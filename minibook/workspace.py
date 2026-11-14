"""Save and open the whole workspace as one file (WS-01 .. WS-06).

A workspace file is a zip holding `workspace.json` (the books, the filter, ticks, per-book choices and the
output settings) and the pictures: the cover in use for every book and every image the user uploaded, so
opening it needs no internet. The Google key and the save folder are never written.
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from . import covers, csvimport as c, imaging, settings as S

FORMAT = "minibook-workspace"
VERSION = 1
EXTENSION = ".minibook"
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


class WorkspaceError(ValueError):
    """The file cannot be opened; the message says why in plain words."""


def _book_to_dict(b: c.Book, group: str) -> dict:
    return {"group": group, "title": b.title, "authors": list(b.authors), "isbn": b.isbn, "asin": b.asin,
            "format": b.format, "status": b.status, "read_date": str(b.read_date) if b.read_date else "",
            "rating": b.rating, "review": b.review, "selected": bool(b.selected), "source": b.source,
            "source_id": b.source_id}


def _book_from_dict(d: dict) -> c.Book:
    if not isinstance(d, dict) or not isinstance(d.get("title"), str) or not d["title"].strip():
        raise WorkspaceError("The file lists a book without a title.")
    try:
        date = c.parse_user_date(d.get("read_date") or "")
        authors = [str(a) for a in d.get("authors") or []]
        rating = d.get("rating")
        rating = float(rating) if rating not in (None, "") else None
    except (ValueError, TypeError) as e:
        raise WorkspaceError(f"A book in the file has unreadable details ({d.get('title')}): {e}") from e
    return c.Book(title=d["title"], authors=authors, isbn=d.get("isbn") or None, asin=d.get("asin") or None,
                  format=str(d.get("format") or ""), status=str(d.get("status") or ""), read_date=date,
                  rating=rating, review=str(d.get("review") or ""), selected=bool(d.get("selected", True)),
                  source="manual" if d.get("source") == "manual" else "csv",
                  source_id=str(d.get("source_id") or ""))


def _index(key) -> int | None:
    try:
        return int(key)
    except (TypeError, ValueError):
        return None


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=95, subsampling=0)
    return buf.getvalue()


def save(ctl) -> bytes:
    """The workspace as bytes: every book (from the CSV and added by hand), choices, covers and uploads."""
    books = [(b, "manual") for b in ctl.manual] + [(b, "csv") for b in ctl.all_books]
    meta = {"format": FORMAT, "version": VERSION, "csv_name": ctl.csv_name,
            "year": ctl.year, "statuses": sorted(ctl.statuses),
            "settings": json.loads(S.export_settings_text(ctl.settings))["settings"],
            "edits": ctl.edits, "books": [], "prefs": {}, "covers": {}, "uploads": {}}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for i, (b, group) in enumerate(books):
            meta["books"].append(_book_to_dict(b, group))
            p = ctl.prefs.get(b.id)
            key = str(i)
            if p is not None:
                d = asdict(p)
                d["custom_path"] = None
                meta["prefs"][key] = d
                if p.custom_path and Path(p.custom_path).exists():
                    name = f"uploads/{i}.png"
                    z.writestr(name, Path(p.custom_path).read_bytes())
                    meta["uploads"][key] = name
            st = ctl.cover_state.get(b.id)
            if st is not None and st.image is not None and not st.custom:
                name = f"covers/{i}.jpg"
                z.writestr(name, _jpeg(st.image))
                meta["covers"][key] = name
        z.writestr("workspace.json", json.dumps(meta, indent=1))
    return out.getvalue()


def _read(z: zipfile.ZipFile, name: str, limit: int, used: list[int]) -> bytes:
    try:
        info = z.getinfo(name)
    except KeyError:
        raise WorkspaceError(f"The file is missing {name}.") from None
    if info.file_size > limit:
        raise WorkspaceError(f"{name} is too large to be a workspace part.")
    used[0] += info.file_size
    if used[0] > MAX_TOTAL_BYTES:
        raise WorkspaceError("The file is too large.")
    return z.read(name)


def load(ctl, data: bytes) -> dict:
    """Replace the current workspace with the one in `data`. Nothing changes if the file is refused."""
    from .controller import CoverState          # local import: controller imports this module

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise WorkspaceError("That is not a MiniBook Studio workspace file.") from None
    used = [0]
    with z:
        try:
            meta = json.loads(_read(z, "workspace.json", MAX_JSON_BYTES, used).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise WorkspaceError("That is not a MiniBook Studio workspace file.") from None
        if not isinstance(meta, dict) or meta.get("format") != FORMAT:
            raise WorkspaceError("That is not a MiniBook Studio workspace file.")
        if not isinstance(meta.get("version"), int) or meta["version"] > VERSION:
            raise WorkspaceError("That workspace was saved by a newer version of the app.")
        raw_books = meta.get("books")
        if not isinstance(raw_books, list):
            raise WorkspaceError("The workspace file has no list of books.")
        books = [(_book_from_dict(d), d.get("group")) for d in raw_books]

        images: dict[int, Image.Image] = {}
        uploads: dict[int, bytes] = {}
        for key, name in (meta.get("covers") or {}).items():
            try:
                images[int(key)] = covers.load_local_image(io.BytesIO(_read(z, name, MAX_IMAGE_BYTES, used)))
            except (covers.CoverError, ValueError, TypeError) as e:
                raise WorkspaceError(f"A saved cover could not be read: {e}") from e
        for key, name in (meta.get("uploads") or {}).items():
            blob = _read(z, name, MAX_IMAGE_BYTES, used)
            try:
                covers.load_local_image(io.BytesIO(blob))
            except covers.CoverError as e:
                raise WorkspaceError(f"A saved upload could not be read: {e}") from e
            if _index(key) is None:
                raise WorkspaceError("The file lists an upload that belongs to no book.")
            uploads[_index(key)] = blob

    # everything is valid: now replace the workspace
    if isinstance(meta.get("settings"), dict):
        res = S.import_settings_text(json.dumps({"format": S.SETTINGS_FILE_FORMAT, "version": S.SETTINGS_VERSION,
                                                 "settings": meta["settings"]}), ctl.settings)
        if res.settings is not None:
            ctl.settings = res.settings
            if ctl.persist:
                S.save_settings(ctl.settings, ctl.settings_path)
    ctl.all_books = [b for b, g in books if g != "manual"]
    ctl.manual = [b for b, g in books if g == "manual"]
    ctl.csv_name = str(meta.get("csv_name") or "")
    ctl.cover_state.clear()
    ctl._thumbs.clear()
    ctl._palettes.clear()
    ctl.pending.clear()
    year = meta.get("year")
    statuses = {str(s) for s in meta.get("statuses") or []} or {"read"}
    ctl.apply_filter(year if isinstance(year, int) else None, statuses)
    for i, (b, _g) in enumerate(books):
        b.selected = bool(raw_books[i].get("selected", True))      # the filter ticked its own defaults

    for key, d in (meta.get("prefs") or {}).items():
        i = _index(key)
        if i is None or not 0 <= i < len(books) or not isinstance(d, dict):
            continue
        b = books[i][0]
        known = {k: v for k, v in d.items() if k in S.BookPrefs.__dataclass_fields__ and k != "custom_path"}
        p = S.BookPrefs()
        for k, v in known.items():                    # keep only values of the right kind
            if k in ("zoom", "pan_x", "pan_y"):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    setattr(p, k, float(v))
            elif k == "spine_color":
                if v is None or (isinstance(v, str) and imaging.from_hex(v)):
                    p.spine_color = v
            elif isinstance(v, str) or v is None:
                setattr(p, k, v)
        ctl.prefs[b.id] = p
    for i, blob in uploads.items():
        if 0 <= i < len(books):
            b = books[i][0]
            ctl.custom_dir.mkdir(parents=True, exist_ok=True)
            path = ctl.custom_dir / f"{b.id}.png"
            covers.load_local_image(io.BytesIO(blob)).save(path, "PNG")
            ctl.prefs.setdefault(b.id, S.BookPrefs()).custom_path = str(path)
    for i, (b, _g) in enumerate(books):
        p = ctl.prefs.get(b.id)
        if i in images:
            ctl.cover_state[b.id] = CoverState(image=images[i], searched=True)
        elif p is not None and ctl.custom_active(p) and p.custom_path and Path(p.custom_path).exists():
            ctl.cover_state[b.id] = CoverState(image=covers.load_local_image(p.custom_path), searched=True, custom=True)
    for k, v in (meta.get("edits") or {}).items():
        if isinstance(v, dict):
            ctl.edits.setdefault(k, v)
    ctl._save_prefs()
    return {"books": len(books), "by_hand": len(ctl.manual), "covers": len(ctl.cover_state)}

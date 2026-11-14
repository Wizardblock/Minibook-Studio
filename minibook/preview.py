"""Fast on-screen preview of the print sheet (EXP-07).

Speed comes from five things: wraps are drawn at screen resolution, not print resolution; each
finished wrap is remembered and redone only when something that affects it changes; settings that
only move wraps around the page (paper, margin, gap, marks) reuse every wrap; only the page being
looked at is built; and stale work can be abandoned between wraps.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Callable

from PIL import Image, ImageDraw

from . import layout, net, settings as S
from .csvimport import Book

PREVIEW_DPI = 110
PROXY_MAX_SIDE = 600        # covers are shrunk once to this, so crop changes never touch full-size images
MAX_CACHED_NETS = 400

# Everything that changes how a single wrap looks. Anything not listed here only moves wraps on the page.
NET_SETTINGS = ("height_mm", "width_mm", "aspect", "size_mode", "thickness_mm", "back_style",
                "back_show_date", "back_show_rating", "back_date_format", "spine_hide_author",
                "spine_drop_subtitle", "spine_min_font_pt", "spine_max_font_pt", "spine_wrap",
                "spine_reverse")


class PreviewCancelled(Exception):
    """Raised inside a render when a newer request made this one pointless."""


@dataclass
class PreviewInput:
    book: Book
    image: Image.Image | None = None      # full-size cover, or None for the placeholder
    zoom: float = 1.0
    pan_x: float = 0.5
    pan_y: float = 0.5
    spine_color: tuple[int, int, int] | None = None     # chosen spine / back color, None = automatic


@dataclass
class PreviewPage:
    image: Image.Image
    page: int                 # zero-based
    pages: int
    per_page: int
    books_on_page: int
    nets_built: int = 0       # how many wraps had to be drawn for this page
    nets_reused: int = 0
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)


def _book_signature(b: Book) -> tuple:
    return (b.title, b.author, b.rating, str(b.read_date) if b.read_date else "")


class PreviewEngine:
    def __init__(self, dpi: int = PREVIEW_DPI, workers: int = 4):
        self.dpi = dpi
        self.workers = workers
        self._nets: OrderedDict[tuple, Image.Image] = OrderedDict()
        self._proxies: dict[int, tuple[Image.Image, Image.Image]] = {}   # id -> (original, small copy)
        self._lock = threading.Lock()
        self.total_built = 0
        self.total_reused = 0

    # -- caches ---------------------------------------------------------------------------
    def clear(self) -> None:
        with self._lock:
            self._nets.clear()
            self._proxies.clear()

    def _proxy(self, img: Image.Image) -> Image.Image:
        with self._lock:
            hit = self._proxies.get(id(img))
            if hit is not None and hit[0] is img:
                return hit[1]
        small = img.convert("RGB")
        if max(small.size) > PROXY_MAX_SIDE:
            small = small.copy()
            small.thumbnail((PROXY_MAX_SIDE, PROXY_MAX_SIDE), Image.Resampling.LANCZOS)
        with self._lock:
            if len(self._proxies) > 200:
                self._proxies.clear()
            self._proxies[id(img)] = (img, small)      # keeping the original alive keeps its id unique
        return small

    def _key(self, item: PreviewInput, s: S.Settings) -> tuple:
        return (_book_signature(item.book),
                id(item.image) if item.image is not None else None,
                round(item.zoom, 4), round(item.pan_x, 4), round(item.pan_y, 4), item.spine_color,
                tuple(getattr(s, n) for n in NET_SETTINGS), self.dpi)

    def _net(self, item: PreviewInput, s: S.Settings, key: tuple) -> tuple[Image.Image, bool]:
        with self._lock:
            hit = self._nets.get(key)
            if hit is not None:
                self._nets.move_to_end(key)
                return hit, True
        small = replace(s, dpi=self.dpi)
        src = self._proxy(item.image) if item.image is not None else None
        img = net.build_net(item.book, src, small, item.zoom, item.pan_x, item.pan_y, item.spine_color).image
        with self._lock:
            self._nets[key] = img
            while len(self._nets) > MAX_CACHED_NETS:
                self._nets.popitem(last=False)
        return img, False

    # -- pages ----------------------------------------------------------------------------
    def grid_for(self, s: S.Settings) -> layout.Grid:
        return layout.make_grid(*s.page_mm, s.net_width_mm, s.height_mm, s.gutter_mm, s.margin_mm)

    def page_count(self, s: S.Settings, n_books: int) -> int:
        try:
            return layout.page_count(n_books, self.grid_for(s))
        except layout.LayoutError:
            return 0

    def hit_test(self, s: S.Settings, n_items: int, page: int, x_px: float, y_px: float) -> int | None:
        """Which book (index into the print-order list) sits under a click on the preview page image?"""
        try:
            grid = self.grid_for(s)
        except layout.LayoutError:
            return None
        px = self.dpi / 25.4
        on_page = min(grid.per_page, max(0, n_items - page * grid.per_page))
        for i in range(on_page):
            cell = grid.cell(i)
            x0, y0 = cell.x_mm * px, cell.y_mm * px
            if x0 <= x_px < x0 + cell.w_mm * px and y0 <= y_px < y0 + cell.h_mm * px:
                return page * grid.per_page + i
        return None

    def render_page(self, items: list[PreviewInput], s: S.Settings, page: int = 0,
                    is_current: Callable[[], bool] | None = None) -> PreviewPage:
        """Draw one sheet. `items` are all selected books in print order; only this page's are built."""
        t0 = time.perf_counter()
        problems = s.validate()
        if problems:
            raise layout.LayoutError("; ".join(problems))
        grid = self.grid_for(s)
        pages = layout.page_count(len(items), grid)
        page = min(max(0, page), max(0, pages - 1))
        chunk = items[page * grid.per_page:(page + 1) * grid.per_page]

        px_mm = self.dpi / 25.4
        pw, ph = s.page_mm
        sheet = Image.new("RGB", (round(pw * px_mm), round(ph * px_mm)), (255, 255, 255))

        keys = [self._key(it, s) for it in chunk]

        def work(i: int):
            if is_current is not None and not is_current():
                raise PreviewCancelled()
            return self._net(chunk[i], s, keys[i])

        built = reused = 0
        if chunk:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                results = list(pool.map(work, range(len(chunk))))
        else:
            results = []
        if is_current is not None and not is_current():
            raise PreviewCancelled()

        draw = ImageDraw.Draw(sheet)
        for i, (img, was_cached) in enumerate(results):
            built += 0 if was_cached else 1
            reused += 1 if was_cached else 0
            cell = grid.cell(i)
            x0, y0 = round(cell.x_mm * px_mm), round(cell.y_mm * px_mm)
            w, h = round(cell.w_mm * px_mm), round(cell.h_mm * px_mm)
            sheet.paste(img.resize((w, h)) if img.size != (w, h) else img, (x0, y0))
            marks = layout.cut_marks(cell, s.gutter_mm)
            if s.fold_marks:
                marks += layout.fold_marks(cell, s.gutter_mm, s.board_width_mm, s.thickness_mm)
            for (ax, ay, bx, by) in marks:
                draw.line([(ax * px_mm, ay * px_mm), (bx * px_mm, by * px_mm)], fill=(0, 0, 0), width=1)
        self.total_built += built
        self.total_reused += reused
        return PreviewPage(sheet, page, pages, grid.per_page, len(chunk), built, reused,
                           time.perf_counter() - t0)

"""Tile nets onto pages and compute cut marks (EXP-02, EXP-03, EXP-05, EXP-06)."""
from __future__ import annotations

from dataclasses import dataclass

from .settings import MARK_OFFSET_MM, MIN_GUTTER_MM, fold_mark_length_mm, mark_length_mm


@dataclass(frozen=True)
class Cell:
    x_mm: float   # left edge, from the page's left
    y_mm: float   # top edge, from the page's top
    w_mm: float
    h_mm: float


@dataclass(frozen=True)
class Grid:
    cols: int
    rows: int
    origin_x_mm: float
    origin_y_mm: float
    net_w_mm: float
    net_h_mm: float
    gutter_mm: float

    @property
    def per_page(self) -> int:
        return self.cols * self.rows

    def cell(self, index_on_page: int) -> Cell:
        r, c = divmod(index_on_page, self.cols)
        return Cell(self.origin_x_mm + c * (self.net_w_mm + self.gutter_mm),
                    self.origin_y_mm + r * (self.net_h_mm + self.gutter_mm),
                    self.net_w_mm, self.net_h_mm)


class LayoutError(ValueError):
    pass


def make_grid(page_w_mm: float, page_h_mm: float, net_w_mm: float, net_h_mm: float,
              gutter_mm: float, margin_mm: float) -> Grid:
    if gutter_mm < MIN_GUTTER_MM:
        raise LayoutError(f"gutter must be at least {MIN_GUTTER_MM} mm")
    if margin_mm < MARK_OFFSET_MM + mark_length_mm(gutter_mm):
        raise LayoutError("page margin is too small for the cut marks")
    usable_w = page_w_mm - 2 * margin_mm
    usable_h = page_h_mm - 2 * margin_mm
    # n nets need n*w + (n-1)*g of space
    cols = int((usable_w + gutter_mm) // (net_w_mm + gutter_mm))
    rows = int((usable_h + gutter_mm) // (net_h_mm + gutter_mm))
    if cols < 1 or rows < 1:
        raise LayoutError("one book does not fit on the page with these margins")
    grid_w = cols * net_w_mm + (cols - 1) * gutter_mm
    # centered horizontally; rows start at the top margin
    ox = (page_w_mm - grid_w) / 2
    return Grid(cols, rows, ox, margin_mm, net_w_mm, net_h_mm, gutter_mm)


def page_count(n_books: int, grid: Grid) -> int:
    return max(1, -(-n_books // grid.per_page)) if n_books else 0


def cut_marks(cell: Cell, gutter_mm: float) -> list[tuple[float, float, float, float]]:
    """Corner marks outside the net as (x1, y1, x2, y2) in mm from the page's top-left.

    Each corner gets one horizontal and one vertical mark, both pointing away from the net and
    both starting MARK_OFFSET_MM from the corner, so no mark ever touches the artwork (EXP-03).
    """
    n = mark_length_mm(gutter_mm)
    if n <= 0:
        return []
    o = MARK_OFFSET_MM
    l, t = cell.x_mm, cell.y_mm
    r, b = l + cell.w_mm, t + cell.h_mm
    marks = []
    for (cx, cy, sx, sy) in ((l, t, -1, -1), (r, t, 1, -1), (l, b, -1, 1), (r, b, 1, 1)):
        marks.append((cx + sx * o, cy, cx + sx * (o + n), cy))   # horizontal, along the net's edge line
        marks.append((cx, cy + sy * o, cx, cy + sy * (o + n)))   # vertical
    return marks


def fold_marks(cell: Cell, gutter_mm: float, cover_w_mm: float, spine_w_mm: float
               ) -> list[tuple[float, float, float, float]]:
    """Short vertical marks above and below the net where the spine meets each cover (EXP-03b).

    They start MARK_OFFSET_MM outside the net like the cut marks, but are shorter, so they read as
    'fold here' rather than 'cut here'.
    """
    n = fold_mark_length_mm(gutter_mm)
    if n <= 0:
        return []
    o = MARK_OFFSET_MM
    t, b = cell.y_mm, cell.y_mm + cell.h_mm
    marks = []
    for fx in (cell.x_mm + cover_w_mm, cell.x_mm + cover_w_mm + spine_w_mm):
        marks.append((fx, t - o, fx, t - o - n))
        marks.append((fx, b + o, fx, b + o + n))
    return marks

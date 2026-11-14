"""Test print page: outlines, labelled spines and a ruler, so a first print shows what is going wrong (TP-*)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import layout, net as netmod, spine, units
from .net import NetResult
from .settings import MARK_OFFSET_MM, Settings, mark_length_mm

SPINE_LABELS = ("Min text size", "Max text size", "Title Wrapped to two lines")
RULER_HEIGHT_MM = 13.0        # from the top margin down to the ruler's line
MARK_CLEAR_MM = 1.5           # space between the longest cut mark and the ruler's line
LINE_PT = 0.25


@dataclass
class TestPrintInfo:
    books_in_row: int
    sample_shown: bool
    ruler_unit: str            # "in" or "mm"
    notes: list[str]


def spine_samples(settings: Settings) -> list[tuple]:
    """(label, spine image, SpineText) for the three labelled spines, drawn on white."""
    cover_w, spine_w, height = netmod.board_pixels(settings)
    lo, hi = settings.spine_min_font_pt, settings.spine_max_font_pt
    kinds = (dict(min_font_pt=lo, max_font_pt=lo),                 # smallest allowed text
             dict(min_font_pt=hi, max_font_pt=hi),                 # largest allowed text (the spine may cap it)
             dict(min_font_pt=lo, max_font_pt=hi, wrap=True, force_wrap=True))
    out = []
    for label, kw in zip(SPINE_LABELS, kinds):
        img, info = spine.render_spine(label, "", spine_w, height, settings.dpi, (255, 255, 255),
                                       hide_author=True, reverse=settings.spine_reverse, **kw)
        out.append((label, img, info))
    return out


def _ruler(c: canvas.Canvas, settings: Settings, x0: float, x1: float, y: float, ph: float) -> str:
    """Ruler along [x0, x1] (mm from the page's left) with its line `y` mm from the top."""
    mm_ruler = settings.unit == "mm"
    step = 1.0 if mm_ruler else 25.4 / 8
    n = int((x1 - x0) / step + 1e-9)
    c.setLineWidth(LINE_PT)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 6)
    base = ph - units.mm_to_pt(y)
    c.line(units.mm_to_pt(x0), base, units.mm_to_pt(x0 + n * step), base)
    for k in range(n + 1):
        x = units.mm_to_pt(x0 + k * step)
        if mm_ruler:
            major, mid = k % 10 == 0, k % 5 == 0
        else:
            major, mid = k % 8 == 0, k % 4 == 0
        h = 4.0 if major else 3.0 if mid else 1.8
        c.line(x, base, x, base + units.mm_to_pt(h))
        if major:
            label = str(k if mm_ruler else k // 8)
            c.drawCentredString(x, base + units.mm_to_pt(h + 0.8), label)
    c.drawString(units.mm_to_pt(x0 + n * step) + 3, base, "mm" if mm_ruler else "inches")
    return "mm" if mm_ruler else "in"


def _outline(c: canvas.Canvas, cell: layout.Cell, ph: float, cover_w: float, spine_w: float) -> None:
    x, w, h = units.mm_to_pt(cell.x_mm), units.mm_to_pt(cell.w_mm), units.mm_to_pt(cell.h_mm)
    y = ph - units.mm_to_pt(cell.y_mm) - h
    c.rect(x, y, w, h, stroke=1, fill=0)
    for fx in (cell.x_mm + cover_w, cell.x_mm + cover_w + spine_w):          # the spine's two edges
        c.line(units.mm_to_pt(fx), y, units.mm_to_pt(fx), y + h)


def _marks(c: canvas.Canvas, settings: Settings, cell: layout.Cell, ph: float) -> None:
    marks = layout.cut_marks(cell, settings.gutter_mm)
    if settings.fold_marks:
        marks += layout.fold_marks(cell, settings.gutter_mm, settings.board_width_mm, settings.thickness_mm)
    for (x1, y1, x2, y2) in marks:
        c.line(units.mm_to_pt(x1), ph - units.mm_to_pt(y1), units.mm_to_pt(x2), ph - units.mm_to_pt(y2))


def export_test_print(settings: Settings, sample: NetResult | None, out_path: str | Path) -> TestPrintInfo:
    problems = settings.validate()
    if problems:
        raise layout.LayoutError("; ".join(problems))
    pw_mm, ph_mm = settings.page_mm
    grid = layout.make_grid(pw_mm, ph_mm, settings.net_width_mm, settings.height_mm,
                            settings.gutter_mm, settings.margin_mm)
    m = settings.margin_mm
    ruler_y = m + RULER_HEIGHT_MM
    y0 = ruler_y + MARK_OFFSET_MM + mark_length_mm(settings.gutter_mm) + MARK_CLEAR_MM
    step = settings.height_mm + settings.gutter_mm
    rows = int((ph_mm - m - y0 + settings.gutter_mm) // step)
    if rows < 1:
        raise layout.LayoutError("the test page does not leave room for a book under the ruler; make the margin smaller")
    pw, ph = units.mm_to_pt(pw_mm), units.mm_to_pt(ph_mm)
    cover_w, spine_w = settings.board_width_mm, settings.thickness_mm
    notes: list[str] = []
    per_row = min(3, grid.cols)
    if per_row < 3:
        notes.append(f"Only {per_row} book(s) fit across this page, so not every spine sample is shown.")

    c = canvas.Canvas(str(out_path), pagesize=(pw, ph))
    c.setTitle("MiniBook Studio test print")
    c.setCreator("MiniBook Studio")
    c.setLineCap(0)
    c.setLineWidth(LINE_PT)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(units.mm_to_pt(m), ph - units.mm_to_pt(m + 2.5), "MiniBook Studio test print")
    c.setFont("Helvetica", 6.5)
    size = lambda v: f"{units.from_mm(v, settings.unit if settings.unit != 'px' else 'in', settings.dpi):.3g}"
    unit = "mm" if settings.unit == "mm" else "in"
    c.drawString(units.mm_to_pt(m + 38), ph - units.mm_to_pt(m + 2.5),
                 f"{settings.paper.upper()}, board {size(settings.board_width_mm)} x {size(settings.height_mm)} x "
                 f"{size(settings.thickness_mm)} {unit}, {settings.dpi} dpi. Print at 100% / actual size; "
                 f"the ruler should measure true.")
    ruler_unit = _ruler(c, settings, m, pw_mm - m, ruler_y, ph)

    c.setLineWidth(LINE_PT)
    c.setStrokeColorRGB(0, 0, 0)
    samples = spine_samples(settings)
    for i in range(per_row):
        cell = layout.Cell(grid.origin_x_mm + i * (grid.net_w_mm + grid.gutter_mm), y0, grid.net_w_mm, grid.net_h_mm)
        label, img, info = samples[i]
        sx = units.mm_to_pt(cell.x_mm + cover_w)
        sh = units.mm_to_pt(cell.h_mm)
        c.drawImage(ImageReader(img), sx, ph - units.mm_to_pt(cell.y_mm) - sh, width=units.mm_to_pt(spine_w), height=sh)
        _outline(c, cell, ph, cover_w, spine_w)
        _marks(c, settings, cell, ph)
        if i == 2 and not info.lines:
            notes.append("This spine is too thin to fit two lines, so the third sample is on one line.")

    shown = False
    if sample is not None and rows >= 2 and grid.cols >= 1:
        cell = layout.Cell(grid.origin_x_mm, y0 + step, grid.net_w_mm, grid.net_h_mm)
        x, w, h = units.mm_to_pt(cell.x_mm), units.mm_to_pt(cell.w_mm), units.mm_to_pt(cell.h_mm)
        c.drawImage(ImageReader(sample.image), x, ph - units.mm_to_pt(cell.y_mm) - h, width=w, height=h)
        _marks(c, settings, cell, ph)
        c.setFont("Helvetica", 6.5)
        c.drawString(x, ph - units.mm_to_pt(cell.y_mm + cell.h_mm + 6), f"Full wrap: {sample.book.title}")
        shown = True
    elif sample is None:
        notes.append("No book is ticked, so there is no full wrap on this page.")
    elif rows < 2:
        notes.append("There is no room for a full wrap under the first row.")
    c.setFont("Helvetica", 6.5)
    ny = y0 + (2 if shown else 1) * step + 4 if shown else y0 + step + 2
    for n in notes:
        ny = min(ny, ph_mm - m)
        c.drawString(units.mm_to_pt(m), ph - units.mm_to_pt(ny), n)
        ny += 3.5
    c.showPage()
    c.save()
    return TestPrintInfo(per_row, shown, ruler_unit, notes)

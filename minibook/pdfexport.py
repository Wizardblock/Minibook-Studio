"""PDF export with ReportLab (EXP-01 .. EXP-06, DIM-06)."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import layout, units
from .net import NetResult
from .settings import Settings

MARK_WIDTH_PT = 0.25


def export_pdf(nets: list[NetResult], settings: Settings, out_path: str | Path) -> layout.Grid:
    """Write all nets to a PDF. Returns the grid used (so callers/tests know where things went)."""
    problems = settings.validate()
    if problems:
        raise layout.LayoutError("; ".join(problems))
    if not nets:
        raise ValueError("no books to export")

    page_w_mm, page_h_mm = settings.page_mm
    grid = layout.make_grid(page_w_mm, page_h_mm, settings.net_width_mm, settings.height_mm,
                            settings.gutter_mm, settings.margin_mm)
    pw, ph = units.mm_to_pt(page_w_mm), units.mm_to_pt(page_h_mm)

    c = canvas.Canvas(str(out_path), pagesize=(pw, ph))
    c.setTitle("MiniBook Studio wraps")
    c.setCreator("MiniBook Studio")
    c.setLineWidth(MARK_WIDTH_PT)
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineCap(0)

    for i, net in enumerate(nets):
        slot = i % grid.per_page
        if i and slot == 0:
            c.showPage()
            c.setLineWidth(MARK_WIDTH_PT)
            c.setStrokeColorRGB(0, 0, 0)
        cell = grid.cell(slot)
        # image fills the cell exactly; PDF y runs bottom-up
        x = units.mm_to_pt(cell.x_mm)
        w = units.mm_to_pt(cell.w_mm)
        h = units.mm_to_pt(cell.h_mm)
        y = ph - units.mm_to_pt(cell.y_mm) - h
        c.drawImage(ImageReader(net.image), x, y, width=w, height=h)
        marks = layout.cut_marks(cell, settings.gutter_mm)
        if settings.fold_marks:
            marks += layout.fold_marks(cell, settings.gutter_mm, settings.board_width_mm, settings.thickness_mm)
        for (x1, y1, x2, y2) in marks:
            c.line(units.mm_to_pt(x1), ph - units.mm_to_pt(y1),
                   units.mm_to_pt(x2), ph - units.mm_to_pt(y2))
    c.showPage()
    c.save()
    return grid

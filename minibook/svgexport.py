"""SVG export: one file per page, real millimetre size, vector marks and the pictures embedded (EXP-10)."""
from __future__ import annotations

import base64
import io
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from PIL import Image

from . import layout
from .net import NetResult
from .settings import Settings

MARK_WIDTH_MM = 0.09          # 0.25 pt, the same as the PDF


def page_paths(out_path: str | Path, pages: int) -> list[Path]:
    """One page keeps the name; several get _page1, _page2 ... before the extension."""
    p = Path(out_path)
    if p.suffix.lower() != ".svg":
        p = p.with_name(p.name + ".svg")
    if pages <= 1:
        return [p]
    return [p.with_name(f"{p.stem}_page{i}{p.suffix}") for i in range(1, pages + 1)]


SVG_MAX_DPI = 300      # a cutter or editor gains nothing from more, and 600 dpi files grow past what many programs can open
JPEG_QUALITY = 95


def _image_data(img, cell_w_mm: float) -> str:
    """The picture as a JPEG data URI, no denser than SVG_MAX_DPI (covers are photographs: PNG was ten times bigger)."""
    target_w = max(1, round(cell_w_mm / 25.4 * SVG_MAX_DPI))
    img = img.convert("RGB")
    if img.width > target_w:
        img = img.resize((target_w, max(1, round(img.height * target_w / img.width))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def export_svg(nets: list[NetResult], settings: Settings, out_path: str | Path) -> list[Path]:
    """Write the pages as SVG files. Returns the paths written."""
    problems = settings.validate()
    if problems:
        raise layout.LayoutError("; ".join(problems))
    if not nets:
        raise ValueError("no books to export")
    pw, ph = settings.page_mm
    grid = layout.make_grid(pw, ph, settings.net_width_mm, settings.height_mm, settings.gutter_mm, settings.margin_mm)
    pages = layout.page_count(len(nets), grid)
    paths = page_paths(out_path, pages)
    for pi, path in enumerate(paths):
        chunk = nets[pi * grid.per_page:(pi + 1) * grid.per_page]
        parts = [f'<?xml version="1.0" encoding="UTF-8"?>\n'
                 f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                 f'width="{pw:g}mm" height="{ph:g}mm" viewBox="0 0 {pw:g} {ph:g}">\n'
                 f'<title>MiniBook Studio wraps, page {pi + 1} of {pages}</title>\n'
                 f'<rect width="{pw:g}" height="{ph:g}" fill="#ffffff"/>\n']
        for slot, n in enumerate(chunk):
            cell = grid.cell(slot)
            marks = layout.cut_marks(cell, settings.gutter_mm)
            fold = layout.fold_marks(cell, settings.gutter_mm, settings.board_width_mm, settings.thickness_mm) \
                if settings.fold_marks else []
            parts.append(f'<g id="book-{pi * grid.per_page + slot + 1}" data-title={quoteattr(n.book.title)}>\n')
            parts.append(f'<title>{escape(n.book.title)}</title>\n')
            parts.append(f'<image x="{cell.x_mm:.3f}" y="{cell.y_mm:.3f}" width="{cell.w_mm:.3f}" '
                         f'height="{cell.h_mm:.3f}" preserveAspectRatio="none" '
                         f'xlink:href="{_image_data(n.image, cell.w_mm)}"/>\n')
            for name, group in (("cut-marks", marks), ("fold-marks", fold)):
                if not group:
                    continue
                parts.append(f'<g id="{name}" stroke="#000000" stroke-width="{MARK_WIDTH_MM}" fill="none">\n')
                for (x1, y1, x2, y2) in group:
                    parts.append(f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}"/>\n')
                parts.append("</g>\n")
            parts.append("</g>\n")
        parts.append("</svg>\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(parts), encoding="utf-8")
    return paths

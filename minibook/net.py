"""Assemble one flat net: [ back ][ spine ][ front ] (NET-01 .. NET-04, DIM-06)."""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from . import backface, imaging, spine, units
from .csvimport import Book
from .settings import Settings


@dataclass
class NetResult:
    image: Image.Image
    book: Book
    spine_info: spine.SpineText | None = None
    warnings: list[str] = field(default_factory=list)
    back_w_px: int = 0
    spine_w_px: int = 0
    front_w_px: int = 0
    color: tuple[int, int, int] | None = None     # the spine / solid-back color that was used


def board_pixels(settings: Settings) -> tuple[int, int, int]:
    """(cover_w_px, spine_w_px, height_px) for the settings' DPI."""
    dpi = settings.dpi
    return (units.mm_to_px(settings.board_width_mm, dpi),
            units.mm_to_px(settings.thickness_mm, dpi),
            units.mm_to_px(settings.height_mm, dpi))


AUTO_HEIGHT_PX = 160


def auto_color(source_cover: Image.Image, aspect: float, zoom: float = 1.0, pan_x: float = 0.5,
               pan_y: float = 0.5) -> imaging.RGB:
    """The automatic spine / back color for a cover and crop. Always worked out on the same small
    rendering, so it does not change with the print resolution or the preview's zoom level."""
    h = AUTO_HEIGHT_PX
    front, _rect, fill = imaging.crop_to_board_ex(source_cover, max(1, round(h * aspect)), h, zoom, pan_x, pan_y)
    return fill if fill is not None else imaging.dominant_color(front)


def build_net(book: Book, source_cover: Image.Image | None, settings: Settings,
              zoom: float = 1.0, pan_x: float = 0.5, pan_y: float = 0.5,
              spine_color: imaging.RGB | None = None) -> NetResult:
    """`spine_color` overrides the automatic spine / back color (and the bars of a zoomed-out cover)."""
    cover_w, spine_w, height = board_pixels(settings)
    warnings: list[str] = []
    fill = None

    if source_cover is None:
        front = imaging.placeholder_cover(cover_w, height)
        warnings.append("no cover found: placeholder used")
    else:
        front, _rect, fill = imaging.crop_to_board_ex(source_cover, cover_w, height, zoom, pan_x, pan_y,
                                                       fill=spine_color)
        loss = imaging.crop_loss(source_cover.width, source_cover.height, cover_w / height)
        if abs(zoom - 1.0) < 1e-6 and loss > imaging.CROP_LOSS_WARN:
            warnings.append(f"center crop discards {loss:.0%} of the image")
        level, dpi = imaging.quality(source_cover.width, source_cover.height,
                                     settings.board_width_mm, settings.height_mm, settings.dpi, zoom)
        if level == "low":
            warnings.append(f"low resolution ({dpi:.0f} dpi at print size)")

    # when the picture was zoomed out, the bars and the spine share one color
    if spine_color:
        base_color = spine_color
    elif source_cover is not None:
        base_color = auto_color(source_cover, cover_w / height, zoom, pan_x, pan_y)
    else:
        base_color = imaging.dominant_color(front)

    if settings.back_style == "complement":
        back = Image.new("RGB", (cover_w, height), base_color)
    elif settings.back_style == "details":     # NET-07: solid colour plus read date and star rating
        date_text = backface.format_date(book.read_date, settings.back_date_format) \
            if settings.back_show_date else ""
        fractions = backface.star_fractions(book.rating) if settings.back_show_rating else None
        back = backface.render_back(base_color, cover_w, height,
                                    date_text=date_text, fractions=fractions)
    else:  # "copy": identical to the front, not mirrored (NET-02)
        back = front.copy()

    spine_img, info = spine.render_spine(
        book.title, book.author, spine_w, height, settings.dpi, base_color,
        hide_author=settings.spine_hide_author, drop_subtitle=settings.spine_drop_subtitle,
        min_font_pt=settings.spine_min_font_pt, max_font_pt=settings.spine_max_font_pt,
        wrap=settings.spine_wrap, reverse=settings.spine_reverse)
    warnings.extend(f"spine: {w}" for w in info.warnings)

    net = Image.new("RGB", (cover_w + spine_w + cover_w, height))
    net.paste(back, (0, 0))
    net.paste(spine_img, (cover_w, 0))
    net.paste(front, (cover_w + spine_w, 0))
    return NetResult(net, book, info, warnings, cover_w, spine_w, cover_w, base_color)

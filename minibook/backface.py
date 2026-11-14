"""Back-cover details: read date and a five-star rating on the solid colour back (NET-07)."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

from . import imaging
from .csvimport import ReadDate
from .spine import font_path

SS = 4                              # drawn at 4x and shrunk, for smooth star edges
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DATE_FORMATS = ("full", "month", "year")      # Mar 5, 2026 / Mar 2026 / 2026
SIDE_MARGIN = 0.10                  # share of the width left empty on each side
STAR_GAP = 0.28                     # gap between stars, in star widths
BLOCK_GAP = 0.55                    # gap between date and stars, in star widths


def format_date(d: ReadDate | None, how: str = "full") -> str:
    """Date text, using as much as the format asks for and as much as the date actually has."""
    if d is None:
        return ""
    if how == "year" or d.month is None:
        return f"{d.year:04d}"
    if how == "month" or d.day is None:
        return f"{MONTHS[d.month - 1]} {d.year:04d}"
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year:04d}"


def star_fractions(rating: float | None) -> list[float] | None:
    """Fill share of each of the five stars, in quarters. None when there is no rating."""
    if rating is None:
        return None
    r = min(5.0, max(0.0, round(float(rating) * 4) / 4))
    return [min(1.0, max(0.0, r - i)) for i in range(5)]


def _star_points(cx: float, cy: float, outer: float) -> list[tuple[float, float]]:
    inner = outer * 0.4
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        r = outer if k % 2 == 0 else inner
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _draw_star(img: Image.Image, cx: float, cy: float, outer: float, fraction: float,
               color: imaging.RGB, line: float) -> None:
    """One star: outline always, solid fill for the left `fraction` of its width."""
    pts = _star_points(cx, cy, outer)
    if fraction > 0:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).polygon(pts, fill=255)
        left = cx - outer * math.sin(2 * math.pi / 5)
        right = cx + outer * math.sin(2 * math.pi / 5)
        cut = left + (right - left) * fraction
        clip = Image.new("L", img.size, 0)
        ImageDraw.Draw(clip).rectangle([0, 0, cut, img.height], fill=255 if fraction < 1 else 255)
        if fraction >= 1:
            clip = Image.new("L", img.size, 255)
        mask = Image.composite(mask, Image.new("L", img.size, 0), clip)
        img.paste(color, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.line(pts + [pts[0]], fill=color, width=max(1, int(round(line))), joint="curve")


def render_back(color: imaging.RGB, width_px: int, height_px: int, *, date_text: str = "",
                fractions: list[float] | None = None) -> Image.Image:
    """The solid back with the date above the stars, centred as one block. Either may be absent."""
    W, H = width_px * SS, height_px * SS
    img = Image.new("RGB", (W, H), color)
    if not date_text and fractions is None:
        return img.resize((width_px, height_px), Image.Resampling.LANCZOS)
    fg = imaging.text_color_for(color)
    avail = W * (1 - 2 * SIDE_MARGIN)
    # star size from the row width: five stars and four gaps
    star_w = avail / (5 + 4 * STAR_GAP)
    outer = star_w / (2 * math.sin(2 * math.pi / 5))
    star_h = outer * (1 + math.cos(math.pi / 5))
    font = None
    text_h = 0.0
    if date_text:
        size = max(6, int(star_w * 0.95))
        font = ImageFont.truetype(font_path(True), size)
        while size > 6 and font.getlength(date_text) > avail:
            size -= 1
            font = ImageFont.truetype(font_path(True), size)
        text_h = float(size)
    block = text_h
    if fractions is not None:
        block += star_h + (BLOCK_GAP * star_w if date_text else 0)
    top = (H - block) / 2
    d = ImageDraw.Draw(img)
    y = top
    if date_text:
        d.text((W / 2, y + text_h / 2), date_text, font=font, fill=fg, anchor="mm")
        y += text_h + BLOCK_GAP * star_w
    if fractions is not None:
        row_w = 5 * star_w + 4 * STAR_GAP * star_w
        x0 = (W - row_w) / 2
        cy = y + outer
        for i, f in enumerate(fractions):
            cx = x0 + star_w / 2 + i * star_w * (1 + STAR_GAP)
            _draw_star(img, cx, cy, outer, f, fg, line=max(1.0, outer * 0.09))
    return img.resize((width_px, height_px), Image.Resampling.LANCZOS)

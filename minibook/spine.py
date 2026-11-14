"""Spine text fitting and rendering (NET-03 .. NET-06)."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import imaging

ELLIPSIS = "…"
SUPERSAMPLE = 3  # text is drawn at 3x and downsampled for smooth small type
SAFE_PAD_MM = 1.0  # clear space at each end of the spine so a slightly-off cut does not clip text


def font_path(bold: bool = True) -> str:
    """Bundled DejaVu Sans Condensed so output is identical on Windows and Linux (SYS-01)."""
    name = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSansCondensed.ttf"
    here = Path(__file__).resolve().parent
    candidates = [here.parent / "assets" / "fonts" / name]
    if getattr(sys, "_MEIPASS", None):  # PyInstaller (SYS-06)
        candidates.insert(0, Path(sys._MEIPASS) / "assets" / "fonts" / name)
    for c in candidates:
        if c.exists():
            return str(c)
    raise FileNotFoundError(f"bundled font {name} not found; looked in {[str(c) for c in candidates]}")


def shorten_title(title: str, drop_subtitle: bool) -> str:
    """Drop a trailing subtitle ('Title: Subtitle') and bracketed series notes."""
    t = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip() or title
    if drop_subtitle and ":" in t:
        head = t.split(":", 1)[0].strip()
        if len(head) >= 2:
            t = head
    return t


@dataclass
class SpineText:
    title: str                 # as drawn (may be shortened / truncated); lines joined by a space
    author: str | None         # None when dropped
    title_pt: float            # physical font size of the title
    author_pt: float | None
    warnings: list[str]        # NET-06
    lines: list[str] | None = None   # the title's two lines when wrapped (NET-05b)


class _Measurer:
    def __init__(self, bold_path: str, reg_path: str):
        self.bold_path, self.reg_path = bold_path, reg_path
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def font(self, which: str, px: int) -> ImageFont.FreeTypeFont:
        key = (which, px)
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(self.bold_path if which == "bold" else self.reg_path, px)
        return self._cache[key]

    def width(self, text: str, which: str, px: int) -> float:
        return self.font(which, px).getlength(text)


TWO_LINE_FACTOR = 0.37   # largest two-line font, as a fraction of the spine thickness


def two_line_cap_pt(thick_mm: float) -> float:
    """Largest font size at which two title lines fit across a spine of this thickness."""
    return thick_mm / 25.4 * 72.0 * TWO_LINE_FACTOR


def wrap_possible(thick_mm: float, min_font_pt: float) -> bool:
    return two_line_cap_pt(thick_mm) >= min_font_pt


def _split_two(words: list[str], width) -> tuple[str, str] | None:
    """Best split of words into two lines (smallest longest line); None for a single word."""
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        w = max(width(a), width(b))
        if best is None or w < best[0]:
            best = (w, a, b)
    return (best[1], best[2]) if best else None


def fit_text(title: str, author: str, length_px: int, thick_px: int, dpi: int, *,
             hide_author: bool = False, drop_subtitle: bool = False,
             min_font_pt: float = 4.0, max_font_pt: float = 99.0, wrap: bool = False,
             force_wrap: bool = False) -> SpineText:
    """Choose what to print and at what size so it always fits (NET-05).

    Order of fallbacks: author shrinks -> author dropped -> title shrinks -> subtitle dropped
    -> title truncated with an ellipsis at the minimum size. Sizes are measured in the
    supersampled space so what is measured is what is drawn.
    """
    ss = SUPERSAMPLE
    L = length_px * ss
    T = thick_px * ss
    pad = int(SAFE_PAD_MM / 25.4 * dpi * ss)   # keep text clear of the cut edges
    avail = L - 2 * pad
    m = _Measurer(font_path(True), font_path(False))
    warnings: list[str] = []

    pt_to_px = dpi * ss / 72.0
    min_px = max(3, int(round(min_font_pt * pt_to_px)))
    max_px = max(min_px, min(int(T * 0.62), int(round(max_font_pt * pt_to_px))))
    gap_factor = 0.9                                # gap between title and author, in title font heights

    def pt(px: int) -> float:
        return px / pt_to_px

    base_title = shorten_title(title, drop_subtitle)
    short_title = shorten_title(title, True)
    author = (author or "").strip()
    want_author = bool(author) and not hide_author and not force_wrap

    def title_fits(t: str, px: int) -> bool:
        return m.width(t, "bold", px) <= avail

    def at_min(tpx: int) -> list[str]:
        return ["text at minimum size"] if tpx <= min_px else []

    # 1) title at full size with the author shrinking first (author never below the minimum)
    if want_author:
        tpx = max_px
        title_w = m.width(base_title, "bold", tpx)
        if title_w + gap_factor * tpx <= avail:
            for apx in range(max(min_px, int(tpx * 0.7)), min_px - 1, -1):
                if title_w + gap_factor * tpx + m.width(author, "reg", apx) <= avail:
                    return SpineText(base_title, author, pt(tpx), pt(apx), warnings + at_min(apx))
        # 2) author dropped, title then shrinks
        warnings.append("author dropped (does not fit)")

    # 3) title alone, shrinking from the largest size (force_wrap, used by the test print, skips to two lines)
    for tpx in range(max_px, min_px - 1, -1) if not force_wrap else ():
        if title_fits(base_title, tpx):
            return SpineText(base_title, None, pt(tpx), None, warnings + at_min(tpx))

    # 4) subtitle dropped, still at >= min size
    if short_title != base_title and not force_wrap:
        for tpx in range(max_px, min_px - 1, -1):
            if title_fits(short_title, tpx):
                return SpineText(short_title, None, pt(tpx), None,
                                 warnings + ["subtitle dropped to fit"] + at_min(tpx))

    # 4b) two lines instead of truncating (NET-05b): the largest size at which they fit
    if wrap:
        two_max = max(min_px, min(max_px, int(T * TWO_LINE_FACTOR)))
        if int(T * TWO_LINE_FACTOR) >= min_px:
            for cand in dict.fromkeys((base_title, short_title)):
                words = cand.split()
                for tpx in range(two_max, min_px - 1, -1):
                    sp = _split_two(words, lambda x: m.width(x, "bold", tpx))
                    if sp and max(m.width(sp[0], "bold", tpx), m.width(sp[1], "bold", tpx)) <= avail:
                        return SpineText(" ".join(sp), None, pt(tpx), None,
                                         warnings + ["title wrapped onto two lines"] + at_min(tpx), list(sp))
            # still too long: first line as many words as fit, second line truncated with an ellipsis
            words = short_title.split()
            tpx = min_px
            first = words[0]
            for i in range(1, len(words)):
                if m.width(" ".join(words[:i + 1]), "bold", tpx) <= avail:
                    first = " ".join(words[:i + 1])
                else:
                    break
            rest = short_title[len(first):].strip()
            while len(first) > 1 and m.width(first, "bold", tpx) > avail:
                first = first[:-1].rstrip()
            second = rest
            if m.width(second, "bold", tpx) > avail:
                while len(second) > 1 and m.width(second + ELLIPSIS, "bold", tpx) > avail:
                    second = second[:-1].rstrip()
                second += ELLIPSIS
            if second:
                return SpineText(f"{first} {second}", None, pt(tpx), None,
                                 warnings + ["title truncated"], [first, second])

    # 5) truncate at the minimum size
    t = short_title
    while len(t) > 1 and not title_fits(t + ELLIPSIS, min_px):
        t = t[:-1].rstrip()
    return SpineText(t + ELLIPSIS, None, pt(min_px), None, warnings + ["title truncated"])


def render_spine(title: str, author: str, width_px: int, height_px: int, dpi: int,
                 bg: imaging.RGB, *, hide_author: bool = False, drop_subtitle: bool = False,
                 min_font_pt: float = 4.0, max_font_pt: float = 99.0,
                 wrap: bool = False, reverse: bool = False,
                 force_wrap: bool = False) -> tuple[Image.Image, SpineText]:
    """Draw the spine as a width_px x height_px image. Text runs along the height."""
    info = fit_text(title, author, height_px, width_px, dpi, hide_author=hide_author,
                    drop_subtitle=drop_subtitle, min_font_pt=min_font_pt,
                    max_font_pt=max_font_pt, wrap=wrap, force_wrap=force_wrap)
    ss = SUPERSAMPLE
    L, T = height_px * ss, width_px * ss
    fg = imaging.text_color_for(bg)
    pt_to_px = dpi * ss / 72.0
    tpx = max(3, int(round(info.title_pt * pt_to_px)))
    canvas = Image.new("RGB", (L, T), bg)                 # drawn horizontally, then rotated
    d = ImageDraw.Draw(canvas)
    bold = ImageFont.truetype(font_path(True), tpx)
    reg = None

    if info.lines:
        pitch = 1.16 * tpx
        for k, line in enumerate(info.lines):
            lw = bold.getlength(line)
            y = T / 2 + (k - (len(info.lines) - 1) / 2) * pitch
            d.text(((L - lw) / 2, y), line, font=bold, fill=fg, anchor="lm")
    elif info.author:
        apx = max(3, int(round(info.author_pt * pt_to_px)))
        reg = ImageFont.truetype(font_path(False), apx)
        tw = bold.getlength(info.title)
        aw = reg.getlength(info.author)
        gap = 0.9 * tpx
        total = tw + gap + aw
        x0 = (L - total) / 2
        d.text((x0, T / 2), info.title, font=bold, fill=fg, anchor="lm")
        d.text((x0 + tw + gap, T / 2), info.author, font=reg, fill=fg, anchor="lm")
    else:
        tw = bold.getlength(info.title)
        d.text(((L - tw) / 2, T / 2), info.title, font=bold, fill=fg, anchor="lm")

    # rotate so the text reads top-to-bottom (US convention); reverse = bottom-to-top
    rotated = canvas.rotate(90 if reverse else -90, expand=True)
    out = rotated.resize((width_px, height_px), Image.Resampling.LANCZOS)
    return out, info

"""Cropping, colors and quality checks (IMG-05, IMG-06, IMG-08, IMG-09, NET-02, NET-03)."""
from __future__ import annotations

import colorsys
from dataclasses import dataclass

from PIL import Image

RGB = tuple[int, int, int]

CROP_LOSS_WARN = 0.25      # IMG-06
QUALITY_OK_RATIO = 0.67    # IMG-05
SHARP_REFERENCE_DPI = 300  # a cover is judged against at most this: printing at 600 dpi does not make a cover blurrier


@dataclass(frozen=True)
class CropWindow:
    left: float
    top: float
    width: float
    height: float

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)


def _base_window(src_w: int, src_h: int, target_aspect: float) -> tuple[float, float]:
    if src_w / src_h > target_aspect:      # source is wider than the board: full height
        return src_h * target_aspect, float(src_h)
    return float(src_w), src_w / target_aspect   # taller/narrower: full width


def min_zoom(src_w: int, src_h: int, target_aspect: float) -> float:
    """Smallest zoom, at which the whole image is just visible (IMG-09b). Always <= 1."""
    bw, bh = _base_window(src_w, src_h, target_aspect)
    return min(1.0, bw / src_w, bh / src_h)


def crop_window(src_w: int, src_h: int, target_aspect: float,
                zoom: float = 1.0, pan_x: float = 0.5, pan_y: float = 0.5) -> CropWindow:
    """Window with `target_aspect` (w/h) over the source, sized by `zoom`.

    zoom 1 is the largest window that fits inside the image (the plain center crop, IMG-08).
    zoom > 1 shrinks the window (zooms in). zoom < 1 grows it past the image edge, down to
    `min_zoom` where the whole image is visible; the part outside the image is filled later.
    pan_x / pan_y are 0..1; 0.5 = centered. Where the window is bigger than the image the pan
    slides the image inside the window.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError("empty image")
    zoom = max(min_zoom(src_w, src_h, target_aspect), float(zoom))
    pan_x = min(1.0, max(0.0, float(pan_x)))
    pan_y = min(1.0, max(0.0, float(pan_y)))
    base_w, base_h = _base_window(src_w, src_h, target_aspect)
    w, h = base_w / zoom, base_h / zoom
    left = pan_x * (src_w - w)
    top = pan_y * (src_h - h)
    return CropWindow(left, top, w, h)


def crop_loss(src_w: int, src_h: int, target_aspect: float) -> float:
    """Fraction of the image discarded by the default crop (IMG-06)."""
    w = crop_window(src_w, src_h, target_aspect)
    return 1.0 - (w.width * w.height) / (src_w * src_h)


def crop_to_board_ex(img: Image.Image, out_w: int, out_h: int, zoom: float = 1.0,
                     pan_x: float = 0.5, pan_y: float = 0.5, fill: RGB | None = None
                     ) -> tuple[Image.Image, tuple[int, int, int, int], RGB | None]:
    """Crop to the board and resize to exactly out_w x out_h.

    Returns (image, picture_rect, fill_color). When zoomed out past the image edge, the area the
    picture does not cover is filled and `fill_color` says with what (None when nothing was filled).
    `picture_rect` is where the picture sits inside the output.
    """
    img = img.convert("RGB")
    win = crop_window(img.width, img.height, out_w / out_h, zoom, pan_x, pan_y)
    l, t, r, b = win.box
    il, it = max(0.0, l), max(0.0, t)
    ir, ib = min(float(img.width), r), min(float(img.height), b)
    sx, sy = out_w / win.width, out_h / win.height
    dx0, dy0 = int(round((il - l) * sx)), int(round((it - t) * sy))
    dx1, dy1 = int(round((ir - l) * sx)), int(round((ib - t) * sy))
    dx0, dy0 = max(0, dx0), max(0, dy0)
    dx1, dy1 = min(out_w, max(dx0 + 1, dx1)), min(out_h, max(dy0 + 1, dy1))
    box = (int(round(il)), int(round(it)), int(round(ir)), int(round(ib)))
    box = (box[0], box[1], min(img.width, max(box[0] + 1, box[2])), min(img.height, max(box[1] + 1, box[3])))
    content = img.crop(box).resize((dx1 - dx0, dy1 - dy0), Image.Resampling.LANCZOS)
    rect = (dx0, dy0, dx1, dy1)
    if rect == (0, 0, out_w, out_h):
        return content, rect, None
    if fill is None:
        fill = dominant_color(content)
    out = Image.new("RGB", (out_w, out_h), fill)
    out.paste(content, (dx0, dy0))
    return out, rect, fill


def crop_to_board(img: Image.Image, out_w: int, out_h: int,
                  zoom: float = 1.0, pan_x: float = 0.5, pan_y: float = 0.5) -> Image.Image:
    return crop_to_board_ex(img, out_w, out_h, zoom, pan_x, pan_y)[0]


def effective_dpi(src_w: int, src_h: int, board_w_mm: float, board_h_mm: float,
                  zoom: float = 1.0) -> float:
    """Resolution the crop actually delivers at print size (IMG-05)."""
    win = crop_window(src_w, src_h, board_w_mm / board_h_mm, zoom)
    return min(win.width / (board_w_mm / 25.4), win.height / (board_h_mm / 25.4))


def quality(src_w: int, src_h: int, board_w_mm: float, board_h_mm: float,
            target_dpi: int, zoom: float = 1.0) -> tuple[str, float]:
    """('good' | 'ok' | 'low', effective_dpi)."""
    dpi = effective_dpi(src_w, src_h, board_w_mm, board_h_mm, zoom)
    ratio = round(dpi / min(target_dpi, SHARP_REFERENCE_DPI), 3)   # absorb float noise: exactly-enough pixels is 'good'
    if ratio >= 1.0:
        return "good", dpi
    if ratio >= QUALITY_OK_RATIO:
        return "ok", dpi
    return "low", dpi


# -- colors -----------------------------------------------------------------------
DARK_VALUE = 0.25        # a pixel whose brightest channel is below this counts as dark
DARK_SHARE = 0.5         # a cover is a "dark cover" when at least this share of it is dark
DARK_GAP = 0.10          # ...and the chosen color is at least this much brighter than the dark pixels' own average


def _dark_average(small: Image.Image) -> tuple[RGB, float]:
    data = small.tobytes()
    dark = [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)
            if max(data[i:i + 3]) / 255 < DARK_VALUE]
    if not dark:
        return (0, 0, 0), 0.0
    n = len(dark)
    avg = tuple(round(sum(p[k] for p in dark) / n) for k in range(3))
    return avg, n / (len(data) // 3)


def dominant_color(img: Image.Image) -> RGB:
    """Most common color cluster of the image (NET-03). Ignores near-white/near-black extremes
    when something more colorful is present so the spine does not turn out blank.

    A mostly dark cover (black background, bright title) is the exception: the clustering blends its
    dark pixels with the bright ones and lands on a washed-out brown or grey, so the spine takes the
    average of the dark pixels instead, which is close to the cover's own black."""
    small = img.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR)
    best = _cluster_color(small)
    dark_avg, share = _dark_average(small)
    if share >= DARK_SHARE and max(best) / 255 - max(dark_avg) / 255 >= DARK_GAP:
        return dark_avg
    return best


def _cluster_color(small: Image.Image) -> RGB:
    q = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)   # [(count, index)]
    scored = []
    for count, idx in counts:
        r, g, b = palette[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        extreme = v > 0.93 and s < 0.12 or v < 0.08
        scored.append((count * (0.25 if extreme else 1.0), (r, g, b)))
    if not scored:
        return (128, 128, 128)
    return max(scored, key=lambda t: t[0])[1]


def fingerprint(img: Image.Image) -> str:
    """A tiny signature of a picture (8x8 colors, as hex), so a choice made for one cover is not applied to another."""
    return img.convert("RGB").resize((8, 8), Image.Resampling.BOX).tobytes().hex()


def same_picture(a: str | None, b: str | None, tolerance: float = 8.0) -> bool:
    """True when two fingerprints are of the same picture (re-saving as JPEG moves the numbers a little)."""
    try:
        x, y = bytes.fromhex(a or ""), bytes.fromhex(b or "")
    except ValueError:
        return False
    if len(x) != 192 or len(y) != 192:
        return False
    return sum(abs(p - q) for p, q in zip(x, y)) / 192 <= tolerance


def to_hex(color: RGB) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in color)


def from_hex(text: str | None) -> RGB | None:
    """'#rrggbb' -> (r, g, b); None for anything else (an unreadable saved value means 'automatic')."""
    t = (text or "").strip()
    if len(t) == 7 and t[0] == "#":
        try:
            return (int(t[1:3], 16), int(t[3:5], 16), int(t[5:7], 16))
        except ValueError:
            return None
    return None


def _distance(a: RGB, b: RGB) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def palette(img: Image.Image, n: int = 6, merge: float = 48.0, edge: float = 30.0) -> list[RGB]:
    """The `n` most common distinct colors of a cover, most common first (the spine color picker).

    Colors closer than `merge` count as one, and ones within `edge` of pure black or white are left out
    (the picker offers black and white itself). Can return fewer than `n` for a flat cover."""
    small = img.convert("RGB").resize((48, 48), Image.Resampling.BOX)
    data = small.tobytes()
    pixels = [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]
    pal = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT).getpalette() or []
    centers = [tuple(pal[i:i + 3]) for i in range(0, min(len(pal), 48), 3)]
    counts = [0] * len(centers)
    for _ in range(3):                                   # a few k-means passes so centers are true averages
        sums = [[0, 0, 0] for _ in centers]
        counts = [0] * len(centers)
        for px in pixels:
            j = min(range(len(centers)), key=lambda k: _distance(px, centers[k]))
            counts[j] += 1
            for c in range(3):
                sums[j][c] += px[c]
        centers = [tuple(round(sums[k][c] / counts[k]) for c in range(3)) if counts[k] else centers[k]
                   for k in range(len(centers))]
    ranked = sorted(zip(counts, centers), reverse=True)
    kept: list[list] = []                                # [count, color]
    for count, col in ranked:
        if count < len(pixels) * 0.03:                   # specks and blended edges are not a cover color
            continue
        for k in kept:
            if _distance(col, k[1]) < merge:
                k[0] += count
                break
        else:
            kept.append([count, col])
    kept.sort(key=lambda k: -k[0])
    out = [tuple(int(c) for c in col) for _n, col in kept
           if _distance(col, (0, 0, 0)) >= edge and _distance(col, (255, 255, 255)) >= edge]
    return out[:n]


def complement(color: RGB) -> RGB:
    """Complementary color (hue + 180 degrees), kept out of the muddy extremes (NET-02)."""
    r, g, b = (c / 255 for c in color)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + 0.5) % 1.0
    s = max(s, 0.35)
    v = min(max(v, 0.35), 0.9)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return (round(r2 * 255), round(g2 * 255), round(b2 * 255))


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: RGB) -> float:
    r, g, b = color
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(a: RGB, b: RGB) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def text_color_for(bg: RGB) -> RGB:
    """Black or white, whichever contrasts more (NET-03)."""
    white, black = (255, 255, 255), (20, 20, 20)
    return white if contrast_ratio(bg, white) >= contrast_ratio(bg, black) else black


def placeholder_cover(w: int, h: int, title: str = "", color: RGB = (205, 200, 190)) -> Image.Image:
    """Used when no cover could be found (IMG-10). Plain, so it is obviously a placeholder."""
    return Image.new("RGB", (w, h), color)

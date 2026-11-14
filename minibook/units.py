"""Unit helpers. Everything is stored in millimetres internally (DIM-03)."""
from __future__ import annotations

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def in_to_mm(v: float) -> float:
    return v * MM_PER_INCH


def mm_to_in(v: float) -> float:
    return v / MM_PER_INCH


def mm_to_pt(v: float) -> float:
    return v / MM_PER_INCH * PT_PER_INCH


def mm_to_px(v: float, dpi: int) -> int:
    return max(1, round(v / MM_PER_INCH * dpi))


UNITS = ("in", "mm", "px")


def to_mm(value: float, unit: str, dpi: int = 300) -> float:
    """Convert a displayed value to millimetres. `px` is pixels at the print resolution `dpi`."""
    if unit == "in":
        return in_to_mm(value)
    if unit == "mm":
        return float(value)
    if unit == "px":
        return float(value) / dpi * MM_PER_INCH
    raise ValueError(f"unknown unit {unit!r}")


def from_mm(value_mm: float, unit: str, dpi: int = 300) -> float:
    if unit == "in":
        return mm_to_in(value_mm)
    if unit == "mm":
        return float(value_mm)
    if unit == "px":
        return value_mm / MM_PER_INCH * dpi
    raise ValueError(f"unknown unit {unit!r}")


def parse_aspect(text: str | float) -> float:
    """Parse an aspect ratio (width / height) from '2:3', '2/3' or '0.667' (DIM-01)."""
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        s = str(text).strip().replace(" ", "")
        if not s:
            raise ValueError("empty aspect ratio")
        for sep in (":", "/", "x", "X"):
            if sep in s:
                a, b = s.split(sep, 1)
                value = float(a) / float(b)
                break
        else:
            value = float(s)
    if not (0.1 <= value <= 10):
        raise ValueError(f"aspect ratio {value} is out of range")
    return value


def scale_dimensions(real_width_in: float, real_height_in: float, real_thickness_in: float,
                     scale: float = 12.0) -> tuple[float, float, float]:
    """Real book size -> miniature size in inches at 1:scale (DIM-04)."""
    if scale <= 0:
        raise ValueError("scale must be positive")
    return real_width_in / scale, real_height_in / scale, real_thickness_in / scale

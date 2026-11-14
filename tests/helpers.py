"""Shared test helpers."""
from __future__ import annotations

import colorsys
import io
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

from minibook.covers import HttpResponse, CoverError

ROOT = Path(__file__).resolve().parent.parent
REAL_CSV = ROOT / "tests" / "data" / "storygraph_export.csv"


def fake_cover(seed: str = "x", w: int = 400, h: int = 600) -> Image.Image:
    rnd = random.Random(seed)
    r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(rnd.random(), 0.6, 0.55))
    im = Image.new("RGB", (w, h), (r, g, b))
    ImageDraw.Draw(im).rectangle([10, 10, w - 10, h - 10], outline=(255, 255, 255), width=3)
    return im


def png_bytes(w: int, h: int, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


class FakeHttp:
    """Stand-in for the network. `routes` maps a URL substring to (status, bytes) or an exception."""

    def __init__(self, routes=None, default=(404, b"")):
        self.routes = routes or {}
        self.default = default
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, timeout=15.0):
        self.calls.append((url, params))
        for needle, resp in self.routes.items():
            if needle in url:
                if isinstance(resp, Exception):
                    raise resp
                if callable(resp):
                    resp = resp(url, params)
                return HttpResponse(*resp)
        return HttpResponse(*self.default)


def json_bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


def gradient_png(w: int, h: int) -> bytes:
    """A non-uniform image, so a different crop window gives different pixels."""
    im = Image.new("RGB", (w, h))
    px = im.load()
    for x in range(w):
        for y in range(h):
            px[x, y] = (int(255 * x / w), int(255 * y / h), 120)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()

"""Punch chroma-key / fake checkerboard backgrounds into a real PNG alpha channel.

Flux and Qwen-Image only emit RGB. When the user asked for a transparent PNG,
image_prompts rewrites the Comfy prompt to a solid magenta (#FF00FF) backdrop.
This module turns that color (or a leftover editor checkerboard) into alpha.
"""

from __future__ import annotations

import io
from collections import deque

from PIL import Image

CHROMA_RGB = (255, 0, 255)
CHROMA_TOL2 = 50 * 50
HOLE_FRACTION = 0.05
MIN_PUNCH_FRACTION = 0.02


def apply_requested_alpha(raw: bytes, *, wanted: bool) -> bytes:
    """Return PNG bytes. Unchanged when transparency was not requested."""
    if not wanted or not raw:
        return raw
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except OSError:
        return raw
    try:
        rgba = im.convert("RGBA")
        if _alpha_hole_fraction(rgba) >= HOLE_FRACTION:
            return raw if im.mode in {"RGBA", "LA"} else _png_bytes(rgba)

        _punch_near_color(rgba, CHROMA_RGB, CHROMA_TOL2, despill=True)
        if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION:
            pair = _border_checker_pair(rgba)
            if pair:
                for color in pair:
                    _punch_near_color(rgba, color, 28 * 28, despill=False)
        if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION:
            _flood_similar_corners(rgba)
        return _png_bytes(rgba)
    finally:
        im.close()


def _png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _alpha_hole_fraction(im: Image.Image) -> float:
    if im.mode != "RGBA":
        return 0.0
    hist = im.getchannel("A").histogram()
    holes = sum(hist[:128])
    return holes / max(1, im.size[0] * im.size[1])


def _dist2(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _despill(r: int, g: int, b: int, chroma: tuple[int, int, int]) -> tuple[int, int, int]:
    if _dist2((r, g, b), chroma) > CHROMA_TOL2 * 4:
        return r, g, b
    mag = min(r, b)
    if mag > g:
        excess = mag - g
        r = max(0, r - excess)
        b = max(0, b - excess)
    return r, g, b


def _punch_near_color(
    rgba: Image.Image,
    rgb: tuple[int, int, int],
    tol2: int,
    *,
    despill: bool,
) -> None:
    out = []
    for pixel in rgba.getdata():
        r, g, b, a = pixel
        if a == 0:
            out.append(pixel)
            continue
        if _dist2((r, g, b), rgb) <= tol2:
            out.append((r, g, b, 0))
            continue
        if despill:
            r, g, b = _despill(r, g, b, rgb)
        out.append((r, g, b, a))
    rgba.putdata(out)


def _tile_mean(im: Image.Image, x: int, y: int, size: int) -> tuple[int, int, int]:
    crop = im.crop((x, y, min(x + size, im.size[0]), min(y + size, im.size[1])))
    sample = crop.convert("RGB").resize((1, 1))
    return sample.getpixel((0, 0))


def _colors_close(
    a: tuple[int, int, int], b: tuple[int, int, int], tol: int = 24
) -> bool:
    return _dist2(a, b) <= tol * tol


def _greyish(color: tuple[int, int, int]) -> bool:
    return max(color) - min(color) <= 40


def _border_checker_pair(
    im: Image.Image, tile: int = 8
) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    rgb = im.convert("RGB")
    width, height = rgb.size
    if width < tile * 4 or height < tile * 4:
        return None
    tiles: list[tuple[int, int, int]] = []
    for x in range(0, width - tile + 1, tile):
        tiles.append(_tile_mean(rgb, x, 0, tile))
        tiles.append(_tile_mean(rgb, x, height - tile, tile))
    for y in range(tile, height - 2 * tile + 1, tile):
        tiles.append(_tile_mean(rgb, 0, y, tile))
        tiles.append(_tile_mean(rgb, width - tile, y, tile))
    if len(tiles) < 8:
        return None
    first = tiles[0]
    second = max(tiles, key=lambda item: _dist2(item, first))
    if _colors_close(first, second, tol=30):
        return None
    if not (_greyish(first) and _greyish(second)):
        return None
    assigned = sum(
        1
        for item in tiles
        if _colors_close(item, first) or _colors_close(item, second)
    )
    if assigned < 0.7 * len(tiles):
        return None
    top = [
        _tile_mean(rgb, x, 0, tile) for x in range(0, width - tile + 1, tile)
    ]
    if len(top) > 2:
        flips = 0
        for prev, cur in zip(top, top[1:]):
            a1 = _colors_close(prev, first)
            b2 = _colors_close(cur, second)
            a2 = _colors_close(prev, second)
            b1 = _colors_close(cur, first)
            if (a1 and b2) or (a2 and b1):
                flips += 1
        if flips < 0.5 * (len(top) - 1):
            return None
    return first, second


def _flood_similar_corners(rgba: Image.Image) -> None:
    corners = [
        _tile_mean(rgba, 0, 0, 8),
        _tile_mean(rgba, max(0, rgba.size[0] - 8), 0, 8),
        _tile_mean(rgba, 0, max(0, rgba.size[1] - 8), 8),
        _tile_mean(rgba, max(0, rgba.size[0] - 8), max(0, rgba.size[1] - 8), 8),
    ]
    base = corners[0]
    if not all(_colors_close(item, base, tol=30) for item in corners[1:]):
        return
    _flood_color(rgba, base, 36 * 36)


def _flood_color(
    rgba: Image.Image, color: tuple[int, int, int], tol2: int
) -> None:
    width, height = rgba.size
    pixels = rgba.load()
    seen = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque(
        ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
    )
    while queue:
        x, y = queue.popleft()
        index = y * width + x
        if seen[index]:
            continue
        seen[index] = 1
        red, green, blue, alpha = pixels[x, y]
        if alpha == 0:
            continue
        if _dist2((red, green, blue), color) > tol2:
            continue
        pixels[x, y] = (red, green, blue, 0)
        if x:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))

"""Punch a real PNG alpha channel out of an RGB Comfy render.

Flux and Qwen-Image only emit RGB. Asking them for "transparent" makes a
Photoshop checkerboard; a fixed magenta chroma-key punches holes in any
subject that uses that color. Prompts request a plain studio background.
This module cuts that background (or leftover chroma / checkerboard / dark
space) away from the subject, for any logo or object.
"""

from __future__ import annotations

import io
from collections import deque

from PIL import Image

CHROMA_RGB = (255, 0, 255)
LIME_RGB = (0, 255, 0)
CHROMA_TOL2 = 50 * 50
HOLE_FRACTION = 0.05
MIN_PUNCH_FRACTION = 0.02
BORDER_MATCH_FRAC = 0.7
BORDER_TOL = 28
DARK_LUMA = 48
DARK_BORDER_FRAC = 0.6


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

        median, match_frac, dark_frac = _border_stats(rgba)
        if match_frac >= BORDER_MATCH_FRAC:
            _flood_from_border(rgba, median, BORDER_TOL * BORDER_TOL)
            if _looks_like_chroma(median):
                _punch_near_color(rgba, median, CHROMA_TOL2, despill=True)
        if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION:
            for chroma in (CHROMA_RGB, LIME_RGB):
                _punch_near_color(rgba, chroma, CHROMA_TOL2, despill=True)
                if _alpha_hole_fraction(rgba) >= MIN_PUNCH_FRACTION:
                    break
        if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION:
            pair = _border_checker_pair(rgba)
            if pair:
                for color in pair:
                    _punch_near_color(rgba, color, 28 * 28, despill=False)
        if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION and dark_frac >= DARK_BORDER_FRAC:
            _flood_dark_from_border(rgba, DARK_LUMA)
        if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION:
            _flood_similar_corners(rgba)
        if _alpha_hole_fraction(rgba) >= MIN_PUNCH_FRACTION:
            _soften_cutout_edge(rgba)
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


def _luma(color: tuple[int, int, int]) -> float:
    return (color[0] * 299 + color[1] * 587 + color[2] * 114) / 1000


def _looks_like_chroma(color: tuple[int, int, int]) -> bool:
    return (
        _dist2(color, CHROMA_RGB) <= CHROMA_TOL2
        or _dist2(color, LIME_RGB) <= CHROMA_TOL2
    )


def _despill(r: int, g: int, b: int, chroma: tuple[int, int, int]) -> tuple[int, int, int]:
    if _dist2((r, g, b), chroma) > CHROMA_TOL2 * 4:
        return r, g, b
    if chroma == LIME_RGB:
        if g > r and g > b:
            excess = g - max(r, b)
            g = max(0, g - excess)
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


def _border_coords(width: int, height: int) -> list[tuple[int, int]]:
    coords = [(x, 0) for x in range(width)]
    coords.extend((x, height - 1) for x in range(width))
    coords.extend((0, y) for y in range(1, height - 1))
    coords.extend((width - 1, y) for y in range(1, height - 1))
    return coords


def _median_rgb(samples: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if not samples:
        return (0, 0, 0)
    mid = len(samples) // 2
    reds = sorted(item[0] for item in samples)
    greens = sorted(item[1] for item in samples)
    blues = sorted(item[2] for item in samples)
    return (reds[mid], greens[mid], blues[mid])


def _border_stats(
    rgba: Image.Image,
) -> tuple[tuple[int, int, int], float, float]:
    width, height = rgba.size
    pixels = rgba.load()
    samples: list[tuple[int, int, int]] = []
    for x, y in _border_coords(width, height):
        r, g, b, _a = pixels[x, y]
        samples.append((r, g, b))
    median = _median_rgb(samples)
    tol2 = BORDER_TOL * BORDER_TOL
    matched = sum(1 for item in samples if _dist2(item, median) <= tol2)
    dark = sum(1 for item in samples if _luma(item) < DARK_LUMA)
    n = max(1, len(samples))
    return median, matched / n, dark / n


def _flood_from_border(
    rgba: Image.Image, color: tuple[int, int, int], tol2: int
) -> None:
    _flood_matching(rgba, start_border=True, match=lambda rgb: _dist2(rgb, color) <= tol2)


def _flood_dark_from_border(rgba: Image.Image, limit: float) -> None:
    _flood_matching(rgba, start_border=True, match=lambda rgb: _luma(rgb) < limit)


def _flood_matching(
    rgba: Image.Image, *, start_border: bool, match
) -> None:
    width, height = rgba.size
    pixels = rgba.load()
    seen = bytearray(width * height)
    if start_border:
        queue: deque[tuple[int, int]] = deque(_border_coords(width, height))
    else:
        queue = deque(
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
        if not match((red, green, blue)):
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


def _soften_cutout_edge(rgba: Image.Image) -> None:
    """Give a 1px half-alpha rim so the cutout is not a hard cookie-cutter."""
    width, height = rgba.size
    pixels = rgba.load()
    edge: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            _r, _g, _b, alpha = pixels[x, y]
            if alpha == 0:
                continue
            neighbors = (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            )
            for nx, ny in neighbors:
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                if pixels[nx, ny][3] == 0:
                    edge.append((x, y))
                    break
    for x, y in edge:
        r, g, b, alpha = pixels[x, y]
        if alpha:
            pixels[x, y] = (r, g, b, min(alpha, 160))


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
    _flood_from_border(rgba, base, 36 * 36)

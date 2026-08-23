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

from PIL import Image, ImageFilter

CHROMA_RGB = (255, 0, 255)
LIME_RGB = (0, 255, 0)
CHROMA_TOL2 = 50 * 50
HOLE_FRACTION = 0.05
MIN_PUNCH_FRACTION = 0.02
BORDER_MATCH_FRAC = 0.55
BORDER_TOL = 36
DARK_LUMA = 48
DARK_BORDER_FRAC = 0.6
DARK_SUBJECT_LUMA = 70
BLOB_MAX_FRAC = 0.12


def apply_requested_alpha(raw: bytes, *, wanted: bool) -> bytes:
    """Return PNG bytes unchanged. Alpha punch is disabled."""
    return raw


def _cut_studio_background(rgba: Image.Image) -> None:
    """Punch leftover studio, checker floors, and border blobs to alpha."""
    pair = _border_checker_pair(rgba)
    if pair:
        for color in pair:
            _flood_from_border(rgba, color, 26 * 26)

    clusters = _border_clusters(rgba)
    center_luma = _center_luma(rgba)
    subject_is_dark = center_luma < DARK_SUBJECT_LUMA
    for color, frac in clusters:
        if frac < 0.12:
            continue
        if _luma(color) < DARK_LUMA and subject_is_dark:
            continue
        _flood_from_border(rgba, color, BORDER_TOL * BORDER_TOL)

    if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION:
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
        if (
            _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION
            and dark_frac >= DARK_BORDER_FRAC
            and not subject_is_dark
        ):
            _flood_dark_from_border(rgba, DARK_LUMA)
        if _alpha_hole_fraction(rgba) < MIN_PUNCH_FRACTION:
            _flood_similar_corners(rgba)

    _grow_transparency(rgba, 32 * 32)
    _remove_small_border_blobs(rgba)


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
        for nx, ny in (
            (x - 1, y),
            (x + 1, y),
            (x, y - 1),
            (x, y + 1),
            (x - 1, y - 1),
            (x + 1, y - 1),
            (x - 1, y + 1),
            (x + 1, y + 1),
        ):
            if 0 <= nx < width and 0 <= ny < height:
                queue.append((nx, ny))


def _soften_cutout_edge(rgba: Image.Image) -> None:
    """Feather the alpha rim so the cutout is not a hard cookie-cutter."""
    alpha = rgba.getchannel("A")
    soft = alpha.filter(ImageFilter.GaussianBlur(radius=1.25))
    rgba.putalpha(soft)


def _edge_tile_means(
    rgb: Image.Image, edge: str, tile: int
) -> list[tuple[int, int, int]]:
    width, height = rgb.size
    tiles: list[tuple[int, int, int]] = []
    if edge == "top":
        for x in range(0, width - tile + 1, tile):
            tiles.append(_tile_mean(rgb, x, 0, tile))
    elif edge == "bottom":
        for x in range(0, width - tile + 1, tile):
            tiles.append(_tile_mean(rgb, x, height - tile, tile))
    elif edge == "left":
        for y in range(0, height - tile + 1, tile):
            tiles.append(_tile_mean(rgb, 0, y, tile))
    else:
        for y in range(0, height - tile + 1, tile):
            tiles.append(_tile_mean(rgb, width - tile, y, tile))
    return tiles


def _flips_between(
    tiles: list[tuple[int, int, int]],
    first: tuple[int, int, int],
    second: tuple[int, int, int],
) -> int:
    if len(tiles) < 3:
        return 0
    flips = 0
    for prev, cur in zip(tiles, tiles[1:]):
        a1 = _colors_close(prev, first)
        b2 = _colors_close(cur, second)
        a2 = _colors_close(prev, second)
        b1 = _colors_close(cur, first)
        if (a1 and b2) or (a2 and b1):
            flips += 1
    return flips


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
    edges = {
        "top": _edge_tile_means(rgb, "top", tile),
        "bottom": _edge_tile_means(rgb, "bottom", tile),
        "left": _edge_tile_means(rgb, "left", tile),
        "right": _edge_tile_means(rgb, "right", tile),
    }
    for row in edges.values():
        tiles.extend(row)
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
    if assigned < 0.55 * len(tiles):
        return None
    for row in edges.values():
        need = max(1, int(0.45 * (len(row) - 1))) if len(row) > 2 else 1
        if _flips_between(row, first, second) >= need:
            return first, second
    return None


def _border_clusters(
    rgba: Image.Image,
) -> list[tuple[tuple[int, int, int], float]]:
    width, height = rgba.size
    pixels = rgba.load()
    samples: list[tuple[int, int, int]] = []
    for x, y in _border_coords(width, height):
        r, g, b, alpha = pixels[x, y]
        if alpha < 16:
            continue
        samples.append((r, g, b))
    if len(samples) < 8:
        return []
    median = _median_rgb(samples)
    second = max(samples, key=lambda item: _dist2(item, median))
    tol2 = BORDER_TOL * BORDER_TOL
    n = max(1, len(samples))
    frac1 = sum(1 for item in samples if _dist2(item, median) <= tol2) / n
    clusters = [(median, frac1)]
    if _dist2(median, second) > 40 * 40:
        frac2 = sum(1 for item in samples if _dist2(item, second) <= tol2) / n
        if frac2 >= 0.12:
            clusters.append((second, frac2))
    return clusters


def _center_luma(rgba: Image.Image) -> float:
    width, height = rgba.size
    crop = rgba.crop((width // 3, height // 3, 2 * width // 3, 2 * height // 3))
    sample = crop.convert("RGB").resize((1, 1))
    return _luma(sample.getpixel((0, 0)))


def _grow_transparency(rgba: Image.Image, tol2: int) -> None:
    """Eat leftover studio pixels that touch already-punched background."""
    width, height = rgba.size
    pixels = rgba.load()
    changed = True
    rounds = 0
    while changed and rounds < 8:
        changed = False
        rounds += 1
        pending: list[tuple[int, int]] = []
        for y in range(height):
            for x in range(width):
                r, g, b, alpha = pixels[x, y]
                if alpha == 0:
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    if pixels[nx, ny][3] != 0:
                        continue
                    nr, ng, nb, _na = pixels[nx, ny]
                    if _dist2((r, g, b), (nr, ng, nb)) <= tol2:
                        pending.append((x, y))
                        break
        for x, y in pending:
            r, g, b, _a = pixels[x, y]
            pixels[x, y] = (r, g, b, 0)
            changed = True


def _remove_small_border_blobs(rgba: Image.Image) -> None:
    """Drop leftover studio islands that still touch the frame."""
    width, height = rgba.size
    pixels = rgba.load()
    seen = bytearray(width * height)
    limit = int(width * height * BLOB_MAX_FRAC)
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if seen[index] or pixels[x, y][3] == 0:
                continue
            stack = [(x, y)]
            component: list[tuple[int, int]] = []
            touches = False
            while stack:
                cx, cy = stack.pop()
                i = cy * width + cx
                if seen[i]:
                    continue
                seen[i] = 1
                if pixels[cx, cy][3] == 0:
                    continue
                component.append((cx, cy))
                if cx == 0 or cy == 0 or cx == width - 1 or cy == height - 1:
                    touches = True
                for nx, ny in (
                    (cx - 1, cy),
                    (cx + 1, cy),
                    (cx, cy - 1),
                    (cx, cy + 1),
                ):
                    if 0 <= nx < width and 0 <= ny < height:
                        stack.append((nx, ny))
            if touches and 1 <= len(component) <= limit:
                for cx, cy in component:
                    r, g, b, _a = pixels[cx, cy]
                    pixels[cx, cy] = (r, g, b, 0)


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

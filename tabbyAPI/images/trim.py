"""Crop a uniform frame (white card border, letterbox) off a raster."""

from __future__ import annotations

import re
from typing import Optional

from PIL import Image

_WHITE_RE = re.compile(r"(?i)\bwhite\b")
_BLACK_RE = re.compile(r"(?i)\bblack\b")

BorderBox = tuple[int, int, int, int]
Rgb = tuple[int, int, int]

DEFAULT_TOL = 32
MIN_CONTENT = 0.9
MIN_SIDE_PX = 2
MIN_KEEP_PX = 8
MIN_KEEP_FRAC = 0.05


def _near(pixel: Rgb, color: Rgb, tol: int) -> bool:
    return (
        abs(pixel[0] - color[0]) <= tol
        and abs(pixel[1] - color[1]) <= tol
        and abs(pixel[2] - color[2]) <= tol
    )


def _median_rgb(samples: list[Rgb]) -> Rgb:
    if not samples:
        return (255, 255, 255)
    mid = len(samples) // 2
    return (
        sorted(item[0] for item in samples)[mid],
        sorted(item[1] for item in samples)[mid],
        sorted(item[2] for item in samples)[mid],
    )


def _corners(pixels, width: int, height: int) -> list[Rgb]:
    return [
        pixels[0, 0][:3],
        pixels[width - 1, 0][:3],
        pixels[0, height - 1][:3],
        pixels[width - 1, height - 1][:3],
    ]


def _span_content_frac(pixels, y: int, x0: int, x1: int, color: Rgb, tol: int) -> float:
    matched = 0
    for x in range(x0, x1):
        if not _near(pixels[x, y][:3], color, tol):
            matched += 1
    return matched / max(1, x1 - x0)


def _col_span_content_frac(pixels, x: int, y0: int, y1: int, color: Rgb, tol: int) -> float:
    matched = 0
    for y in range(y0, y1):
        if not _near(pixels[x, y][:3], color, tol):
            matched += 1
    return matched / max(1, y1 - y0)


def _content_bbox(pixels, width: int, height: int, color: Rgb, tol: int) -> Optional[BorderBox]:
    left, top, right, bottom = width, height, 0, 0
    found = False
    for y in range(height):
        for x in range(width):
            if _near(pixels[x, y][:3], color, tol):
                continue
            found = True
            if x < left:
                left = x
            if y < top:
                top = y
            if x + 1 > right:
                right = x + 1
            if y + 1 > bottom:
                bottom = y + 1
    if not found:
        return None
    return (left, top, right, bottom)


def trim_box(
    image: Image.Image,
    *,
    color: Optional[Rgb] = None,
    tol: int = DEFAULT_TOL,
    min_content: float = MIN_CONTENT,
) -> Optional[BorderBox]:
    """Axis-aligned crop that drops a flat edge color.

    First crop to the bounding box of non-frame pixels, then shrink past
    rounded-corner leftovers so a white card frame becomes a tight rectangle.
    """
    if image.width < MIN_KEEP_PX or image.height < MIN_KEEP_PX:
        return None
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    if color is None:
        corners = _corners(pixels, width, height)
        if not all(_near(item, corners[0], tol) for item in corners[1:]):
            return None
        color = _median_rgb(corners)

    box = _content_bbox(pixels, width, height, color, tol)
    if box is None:
        return None
    left, top, right, bottom = box

    while top < bottom and _span_content_frac(pixels, top, left, right, color, tol) < min_content:
        top += 1
    while bottom > top and _span_content_frac(pixels, bottom - 1, left, right, color, tol) < min_content:
        bottom -= 1
    while left < right and _col_span_content_frac(pixels, left, top, bottom, color, tol) < min_content:
        left += 1
    while right > left and _col_span_content_frac(pixels, right - 1, top, bottom, color, tol) < min_content:
        right -= 1

    if left == 0 and top == 0 and right == width and bottom == height:
        return None
    if left > 0 and left < MIN_SIDE_PX:
        left = 0
    if top > 0 and top < MIN_SIDE_PX:
        top = 0
    if right < width and width - right < MIN_SIDE_PX:
        right = width
    if bottom < height and height - bottom < MIN_SIDE_PX:
        bottom = height
    if left == 0 and top == 0 and right == width and bottom == height:
        return None
    keep_w = right - left
    keep_h = bottom - top
    if keep_w < MIN_KEEP_PX or keep_h < MIN_KEEP_PX:
        return None
    if keep_w * keep_h < width * height * MIN_KEEP_FRAC:
        return None
    return (left, top, right, bottom)


def trim_image(
    image: Image.Image,
    *,
    color: Optional[Rgb] = None,
    tol: int = DEFAULT_TOL,
    min_content: float = MIN_CONTENT,
) -> tuple[Image.Image, Optional[BorderBox]]:
    """Return (cropped image, box). Box is None when nothing was cropped."""
    box = trim_box(image, color=color, tol=tol, min_content=min_content)
    if box is None:
        return image, None
    return image.crop(box), box


def preferred_border_color(text: str) -> Optional[Rgb]:
    raw = text or ""
    if _WHITE_RE.search(raw):
        return (255, 255, 255)
    if _BLACK_RE.search(raw):
        return (0, 0, 0)
    return None

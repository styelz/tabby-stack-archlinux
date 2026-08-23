#!/usr/bin/env python3
"""Draw management-UI mock screenshots with sample data. No GPU / no live server.

Outputs JPGs under docs/ for the README. Re-run:

  python3 docs/make_ui_screenshots.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE
FONT_SANS = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")
FONT_MONO = Path("/usr/share/fonts/Adwaita/AdwaitaMono-Regular.ttf")

W, H = 1280, 820
BG = (11, 13, 18)
ELEV = (18, 21, 28)
ELEV2 = (24, 28, 38)
LINE = (40, 44, 54)
TEXT = (232, 236, 244)
MUTED = (154, 163, 181)
ACCENT = (122, 162, 255)
ACCENT2 = (139, 92, 246)
OK = (61, 214, 140)
WARN = (245, 197, 66)
BAD = (255, 107, 122)
CHART_BG = (7, 8, 12)


def font(size: int, *, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_MONO if mono else FONT_SANS
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def rr(draw: ImageDraw.ImageDraw, box, radius: int, fill, outline=None, width: int = 1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def header(img: Image.Image, active: str) -> ImageDraw.ImageDraw:
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, 64), fill=(14, 16, 22))
    draw.line((0, 64, W, 64), fill=LINE)

    # brand mark
    mark = Image.new("RGBA", (42, 42), (0, 0, 0, 0))
    md = ImageDraw.Draw(mark)
    md.rounded_rectangle((0, 0, 41, 41), 12, fill=ACCENT)
    for i, color in enumerate((ACCENT, ACCENT2, OK)):
        md.pieslice((2, 2, 39, 39), i * 120, i * 120 + 120, fill=color)
    img.paste(mark, (18, 11), mark)

    draw.text((72, 12), "TABBY STACK", fill=MUTED, font=font(11))
    titles = {"logs": "Logs", "chat": "Chat", "status": "Status", "gallery": "Gallery"}
    draw.text((72, 28), titles[active], fill=TEXT, font=font(18))

    tabs = [("logs", "Logs"), ("chat", "Chat"), ("status", "Status"), ("gallery", "Gallery")]
    x = 280
    for key, label in tabs:
        tw = 78
        box = (x, 16, x + tw, 48)
        if key == active:
            rr(draw, box, 999, fill=ELEV2, outline=LINE)
            draw.text((x + 18, 24), label, fill=TEXT, font=font(14))
        else:
            draw.text((x + 18, 24), label, fill=MUTED, font=font(14))
        x += tw + 8

    # chips
    rr(draw, (W - 320, 18, W - 190, 46), 999, fill=(30, 50, 40), outline=(50, 100, 70))
    draw.text((W - 308, 24), "LLM · qwen", fill=OK, font=font(12))
    rr(draw, (W - 180, 18, W - 100, 46), 999, fill=None, outline=LINE)
    draw.text((W - 168, 24), "pbp", fill=MUTED, font=font(12))
    draw.text((W - 88, 24), "Log out", fill=MUTED, font=font(12))
    return draw


def card(draw: ImageDraw.ImageDraw, box, title: str, value: str, extra: str = ""):
    rr(draw, box, 14, fill=ELEV, outline=LINE)
    x0, y0, x1, y1 = box
    draw.text((x0 + 16, y0 + 14), title, fill=MUTED, font=font(13))
    draw.text((x0 + 16, y0 + 40), value, fill=TEXT, font=font(20))
    if extra:
        draw.text((x0 + 16, y0 + 72), extra[:48], fill=MUTED, font=font(12))


def spark_series(n: int, base: float, amp: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    vals = []
    v = base
    for i in range(n):
        v += rng.uniform(-amp, amp) + 0.15 * math.sin(i / 7.0)
        v = max(5.0, min(98.0, v))
        vals.append(v)
    return vals


def draw_chart(
    draw: ImageDraw.ImageDraw,
    box,
    title: str,
    legend: list[tuple[str, tuple[int, int, int]]],
    series: list[tuple[tuple[int, int, int], list[float]]],
    y_max: float = 100.0,
):
    rr(draw, box, 12, fill=CHART_BG, outline=LINE)
    x0, y0, x1, y1 = box
    draw.text((x0 + 14, y0 + 10), title, fill=TEXT, font=font(13))
    lx = x0 + 90
    for label, color in legend:
        draw.ellipse((lx, y0 + 14, lx + 8, y0 + 22), fill=color)
        draw.text((lx + 12, y0 + 10), label, fill=MUTED, font=font(11))
        lx += 14 + draw.textlength(label, font=font(11)) + 14

    plot = (x0 + 44, y0 + 40, x1 - 14, y1 - 28)
    px0, py0, px1, py1 = plot
    draw.rectangle(plot, fill=(12, 14, 18))
    for i in range(5):
        y = py0 + (py1 - py0) * i / 4
        draw.line((px0, y, px1, y), fill=LINE)
        val = int(y_max * (1 - i / 4))
        draw.text((px0 - 36, y - 6), str(val), fill=MUTED, font=font(10, mono=True))

    for color, vals in series:
        if len(vals) < 2:
            continue
        pts = []
        for i, v in enumerate(vals):
            x = px0 + (px1 - px0) * i / (len(vals) - 1)
            y = py1 - (py1 - py0) * min(y_max, max(0, v)) / y_max
            pts.append((x, y))
        draw.line(pts, fill=color, width=2)

    # time labels
    for i, label in enumerate(("14:00", "16:00", "18:00", "20:00", "now")):
        x = px0 + (px1 - px0) * i / 4
        draw.text((x - 14, py1 + 8), label, fill=MUTED, font=font(10, mono=True))


def make_status() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = header(img, "status")

    rr(draw, (18, 80, 100, 112), 10, fill=ELEV2, outline=LINE)
    draw.text((36, 88), "Refresh", fill=TEXT, font=font(13))
    draw.text((W - 220, 88), "2026-08-24T04:12:08Z", fill=MUTED, font=font(12, mono=True))

    # Left stacked panels
    side_x0, side_x1 = 18, 310
    cards = [
        ("GPU mode", "llm", "Comfy idle"),
        ("Profile", "qwen", "Qwen3.5-9B-exl3-4.00bpw"),
        ("Context", "262144", "cache FP8"),
        ("Health", "healthy", "no issues"),
        ("Uptime", "3h 42m", "http://gpu-host:5000/v1"),
        ("NVIDIA", "RTX 4070 Ti", "8142 / 12282 MiB · 62% · 61°C"),
        ("CPU / load", "28%", "load 1.84"),
        ("RAM", "47%", ""),
    ]
    y = 124
    for t, v, e in cards:
        box = (side_x0, y, side_x1, y + 62)
        rr(draw, box, 12, fill=ELEV, outline=LINE)
        draw.text((side_x0 + 12, y + 8), t, fill=MUTED, font=font(11))
        draw.text((side_x0 + 12, y + 26), v, fill=TEXT, font=font(16))
        if e:
            draw.text((side_x0 + 12, y + 46), e[:42], fill=MUTED, font=font(11))
        y += 68

    rr(draw, (side_x0, y, side_x1, min(H - 18, y + 170)), 14, fill=ELEV, outline=LINE)
    draw.text((side_x0 + 14, y + 12), "Actions", fill=MUTED, font=font(13))
    for i, label in enumerate(("qwen ▾", "Load LLM", "Hand GPU to Comfy", "Restart stack")):
        by = y + 38 + i * 32
        if by + 26 > H - 28:
            break
        fill = (58, 24, 30) if "Restart" in label else ELEV2
        outline = (120, 50, 60) if "Restart" in label else LINE
        rr(draw, (side_x0 + 12, by, side_x1 - 12, by + 26), 8, fill=fill, outline=outline)
        draw.text((side_x0 + 22, by + 5), label, fill=TEXT, font=font(12))

    # Right graphs panel
    panel = (322, 124, W - 18, H - 18)
    rr(draw, panel, 14, fill=ELEV, outline=LINE)
    draw.text((338, 138), "Graphs", fill=TEXT, font=font(13))

    # compact segmented range
    seg_x = 400
    segs = (("1h", False), ("6h", False), ("24h", True), ("7d", False), ("30d", False))
    rr(draw, (seg_x, 134, seg_x + 5 * 42, 160), 8, fill=BG, outline=LINE)
    for i, (label, on) in enumerate(segs):
        x0 = seg_x + i * 42
        if on:
            draw.rectangle((x0 + 1, 135, x0 + 41, 159), fill=(40, 55, 90))
            draw.text((x0 + 10, 140), label, fill=TEXT, font=font(12))
        else:
            draw.text((x0 + 10, 140), label, fill=MUTED, font=font(12))
        if i < 4:
            draw.line((x0 + 42, 136, x0 + 42, 158), fill=LINE)

    # custom amount + unit + Go
    cx = seg_x + 5 * 42 + 10
    rr(draw, (cx, 134, cx + 118, 160), 8, fill=BG, outline=LINE)
    draw.text((cx + 8, 140), "24", fill=TEXT, font=font(12, mono=True))
    draw.line((cx + 40, 136, cx + 40, 158), fill=LINE)
    draw.text((cx + 48, 140), "h ▾", fill=MUTED, font=font(12))
    draw.line((cx + 78, 136, cx + 78, 158), fill=LINE)
    draw.text((cx + 88, 140), "Go", fill=ACCENT, font=font(12))
    draw.text((W - 200, 140), "240 pts · 24h · ~30s", fill=MUTED, font=font(11))

    n = 48
    gpu = spark_series(n, 55, 12, 1)
    vram = spark_series(n, 68, 6, 2)
    temp = [min(85, 45 + v * 0.35) for v in gpu]
    cpu = spark_series(n, 25, 10, 3)
    ram = spark_series(n, 45, 4, 4)
    load = [v / 10 for v in spark_series(n, 18, 8, 5)]

    mid = (124 + H - 18) // 2 + 20
    draw_chart(
        draw,
        (338, 172, W - 34, mid - 6),
        "GPU",
        [("util %", ACCENT), ("VRAM %", ACCENT2), ("°C", WARN)],
        [(ACCENT, gpu), (ACCENT2, vram), (WARN, temp)],
    )
    draw_chart(
        draw,
        (338, mid + 6, W - 34, H - 34),
        "Host",
        [("CPU %", OK), ("RAM %", BAD), ("load×10", MUTED)],
        [(OK, cpu), (BAD, ram), (MUTED, [v * 10 for v in load])],
    )
    return img


def make_logs() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = header(img, "logs")
    rr(draw, (18, 80, 100, 112), 10, fill=ELEV2, outline=LINE)
    draw.text((40, 88), "Pause", fill=TEXT, font=font(13))
    rr(draw, (110, 80, 420, 112), 10, fill=BG, outline=LINE)
    draw.text((122, 88), "Filter logs…", fill=MUTED, font=font(13))

    rr(draw, (18, 124, W - 18, H - 18), 14, fill=CHART_BG, outline=LINE)
    lines = [
        ("info", "2026-08-24 04:10:01 | INFO     | Management UI: http://127.0.0.1:5000/v1/ui"),
        ("info", "2026-08-24 04:10:02 | INFO     | Starting OAI API"),
        ("debug", "2026-08-24 04:10:33 | DEBUG    | Metrics sample recorded (cpu=22.1 gpu=58)"),
        ("info", "2026-08-24 04:11:02 | INFO     | [comfy] idle"),
        ("warn", "2026-08-24 04:11:18 | WARNING  | Client disconnected during stream"),
        ("info", "2026-08-24 04:11:40 | INFO     | Chat completion finished tokens=842"),
        ("info", "2026-08-24 04:12:01 | INFO     | GPU mode=llm profile=qwen"),
        ("error", "2026-08-24 04:12:14 | ERROR    | (example) image job cancelled by restart"),
        ("info", "2026-08-24 04:12:40 | INFO     | Health check ok"),
        ("info", "2026-08-24 04:13:02 | INFO     | Switch to qwen complete (~65s)"),
    ]
    colors = {
        "info": (183, 196, 255),
        "debug": (138, 147, 166),
        "warn": WARN,
        "error": (255, 139, 150),
    }
    y = 140
    for kind, line in lines:
        draw.text((34, y), line, fill=colors[kind], font=font(12, mono=True))
        y += 22
    return img


def make_gallery() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = header(img, "gallery")
    rr(draw, (18, 80, 110, 112), 10, fill=ELEV2, outline=LINE)
    draw.text((36, 88), "Refresh", fill=TEXT, font=font(13))
    rr(draw, (120, 80, 230, 112), 10, fill=(58, 24, 30), outline=(120, 50, 60))
    draw.text((138, 88), "Delete…", fill=BAD, font=font(13))
    draw.text((W - 160, 88), "Page 1 / 3", fill=MUTED, font=font(13))

    thumbs = [
        ("generated-20260824-031201-1122.png", (40, 70, 120)),
        ("generated-20260824-031508-1188.png", (120, 50, 90)),
        ("generated-20260824-032044-1201.png", (30, 90, 140)),
        ("harbor-logo.png", (200, 160, 60)),
        ("harbor-header.png", (20, 40, 90)),
        ("cosmos-logo.png", (90, 40, 140)),
        ("mars.png", (160, 70, 40)),
        ("neptune.png", (30, 60, 160)),
    ]
    gap, tw, th = 14, 290, 210
    for i, (name, color) in enumerate(thumbs):
        col, row = i % 4, i // 4
        x = 18 + col * (tw + gap)
        y = 128 + row * (th + gap)
        rr(draw, (x, y, x + tw, y + th), 12, fill=ELEV, outline=LINE)
        # fake image area with gradient-ish blocks
        for band in range(6):
            c = tuple(max(0, min(255, int(v + band * 8 - 20))) for v in color)
            draw.rectangle((x + 1, y + 1 + band * 28, x + tw - 1, y + 1 + (band + 1) * 28), fill=c)
        draw.rectangle((x + 1, y + th - 44, x + tw - 1, y + th - 1), fill=ELEV)
        draw.text((x + 12, y + th - 32), name[:34], fill=MUTED, font=font(11))
        # checkbox
        rr(draw, (x + tw - 36, y + 10, x + tw - 12, y + 34), 6, fill=(0, 0, 0), outline=LINE)
    return img


def make_chat() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = header(img, "chat")
    rr(draw, (18, 80, 118, 112), 10, fill=ELEV2, outline=LINE)
    draw.text((36, 88), "New chat", fill=TEXT, font=font(13))
    rr(draw, (128, 80, 268, 112), 10, fill=(58, 24, 30), outline=(120, 50, 60))
    draw.text((142, 88), "Clear history", fill=BAD, font=font(13))
    draw.text((286, 88), "1/3 · What model is loaded, and is the GPU…", fill=MUTED, font=font(13))
    draw.text((W - 280, 88), "Tab previous chats · ↑↓ scroll", fill=MUTED, font=font(12))
    rr(draw, (18, 124, W - 18, H - 90), 14, fill=ELEV, outline=LINE)

    bubbles = [
        ("user", "What model is loaded, and is the GPU free for images?"),
        (
            "assistant",
            "You're on qwen (Qwen3.5-9B). GPU mode is llm — Comfy is idle.\n"
            "Send switch to comfy when you want Flux / Qwen-Image, or generate an image of …\n"
            "from your editor and the API will hand the card over.",
        ),
        ("user", "Show GPU memory roughly."),
        (
            "assistant",
            "About 8.1 / 12.3 GiB in use at 61°C, util ~60%. Status → Host graphs has the last 24h.",
        ),
    ]
    y = 144
    for role, text in bubbles:
        if role == "user":
            box_w = 520
            x0 = W - 40 - box_w
            rr(draw, (x0, y, x0 + box_w, y + 70), 12, fill=(40, 55, 90))
            draw.multiline_text((x0 + 14, y + 14), text, fill=TEXT, font=font(14), spacing=4)
            y += 90
        else:
            box_w = 640
            x0 = 40
            lines = text.count("\n") + 1
            bh = 28 + lines * 22
            rr(draw, (x0, y, x0 + box_w, y + bh), 12, fill=ELEV2, outline=LINE)
            draw.multiline_text((x0 + 14, y + 12), text, fill=TEXT, font=font(14), spacing=4)
            y += bh + 20

    rr(draw, (18, H - 74, W - 120, H - 18), 12, fill=BG, outline=LINE)
    draw.text((34, H - 54), "Message the console…", fill=MUTED, font=font(14))
    rr(draw, (W - 108, H - 74, W - 18, H - 18), 12, fill=ACCENT)
    draw.text((W - 88, H - 54), "Send", fill=BG, font=font(14))
    return img


def save_jpg(img: Image.Image, name: str) -> Path:
    path = OUT / name
    img = img.convert("RGB")
    img.save(path, "JPEG", quality=88, optimize=True)
    print(f"wrote {path} ({path.stat().st_size // 1024} KiB)")
    return path


def main() -> None:
    save_jpg(make_status(), "ui-status.jpg")
    save_jpg(make_logs(), "ui-logs.jpg")
    save_jpg(make_gallery(), "ui-gallery.jpg")
    save_jpg(make_chat(), "ui-chat.jpg")


if __name__ == "__main__":
    main()

#!/usr/bin/python
"""CPU-rendered KMSDRM kiosk: stack activity as a thermal field.

Does not import TabbyAPI or CUDA. Polls GET /v1/ui/saver/state on localhost.
Software SDL only — do not point this at a GL renderer on the LLM GPU.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

BG = (11, 13, 18)
TEXT = (232, 236, 244)
MUTED = (154, 163, 181)
ACCENT = (122, 162, 255)
ACCENT2 = (139, 92, 246)
WARN = (245, 197, 66)
OK = (61, 214, 140)
NAVY = (18, 24, 38)
AMBER_DIM = (48, 34, 12)
GREEN_DIM = (12, 42, 32)

SIN_BITS = 12
SIN_SIZE = 1 << SIN_BITS
SIN_MASK = SIN_SIZE - 1
SIN_LUT = [math.sin(i * (2.0 * math.pi / SIN_SIZE)) for i in range(SIN_SIZE)]
TWO_PI = 2.0 * math.pi


def lsin(x: float) -> float:
    return SIN_LUT[int(x * (SIN_SIZE / TWO_PI)) & SIN_MASK]


def _mix(c0: tuple[int, int, int], c1: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return (
        int(c0[0] + (c1[0] - c0[0]) * t),
        int(c0[1] + (c1[1] - c0[1]) * t),
        int(c0[2] + (c1[2] - c0[2]) * t),
    )


def _palette(stops: list[tuple[float, tuple[int, int, int]]]) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for i in range(256):
        t = i / 255.0
        color = stops[-1][1]
        for j in range(len(stops) - 1):
            p0, c0 = stops[j]
            p1, c1 = stops[j + 1]
            if t <= p1 or j == len(stops) - 2:
                span = p1 - p0
                u = 0.0 if span <= 0 else (t - p0) / span
                color = _mix(c0, c1, u)
                break
        out.append(color)
    return out


PALETTES = {
    "idle": _palette([(0.0, BG), (0.5, NAVY), (1.0, (38, 52, 88))]),
    "chat": _palette([(0.0, BG), (0.32, (28, 40, 82)), (0.68, ACCENT), (1.0, ACCENT2)]),
    "image": _palette([(0.0, BG), (0.38, AMBER_DIM), (1.0, WARN)]),
    "switch": _palette([(0.0, BG), (0.4, GREEN_DIM), (1.0, OK)]),
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def saver_url(base: str) -> str:
    root = (base or "http://127.0.0.1:5000").rstrip("/")
    return f"{root}/v1/ui/saver/state"


def fetch_state(url: str, timeout: float = 0.8) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _exp_approach(current: float, target: float, dt: float, tau: float) -> float:
    if tau <= 0.0:
        return target
    return current + (target - current) * (1.0 - math.exp(-dt / tau))


class SceneFollow:
    """Hold one continuous field: never snap phase, palette, or HUD on a poll."""

    _HOLD_LIVE_S = 5.0
    _TAU_S = 2.4

    def __init__(self) -> None:
        self.intensity = 0.28
        self.speed = 0.09
        self.heat = 0.15
        self.util = 0.0
        self.vram = 0.0
        self.temp = 40.0
        self.st = 0.0
        self.live = False
        self._live_until = 0.0
        self.weights = {name: (1.0 if name == "idle" else 0.0) for name in PALETTES}
        self.phase = "idle"
        self.palette = "idle"
        self.mode = "—"
        self.profile = "—"
        self.connected = False

    def _hold_live(self, want: bool, now: float) -> bool:
        if want:
            self._live_until = now + self._HOLD_LIVE_S
            return True
        return now < self._live_until

    def tick(self, target: dict[str, Any], dt: float, now: float) -> dict[str, Any]:
        dt = 0.0 if dt < 0.0 else 0.08 if dt > 0.08 else dt
        want_live = bool(target.get("live"))
        self.live = self._hold_live(want_live, now)
        self.intensity = _exp_approach(self.intensity, float(target["intensity"]), dt, self._TAU_S)
        self.speed = _exp_approach(self.speed, float(target["speed"]), dt, self._TAU_S)
        self.heat = _exp_approach(self.heat, float(target["heat"]), dt, self._TAU_S)
        self.util = _exp_approach(self.util, float(target["util"]), dt, 1.6)
        self.vram = _exp_approach(self.vram, float(target["vram"]), dt, 1.6)
        self.temp = _exp_approach(self.temp, float(target["temp"]), dt, 2.0)
        self.st += self.speed * dt
        dest = str(target.get("palette") or "idle")
        if dest not in self.weights:
            dest = "idle"
        for name in self.weights:
            goal = 1.0 if name == dest else 0.0
            self.weights[name] = _exp_approach(self.weights[name], goal, dt, 1.8)
        self.palette = max(self.weights, key=lambda name: self.weights[name])
        self.mode = str(target.get("mode") or self.mode)
        self.profile = str(target.get("profile") or self.profile)
        self.connected = bool(target.get("connected"))
        if not self.connected:
            self.phase = "waiting for api"
        elif self.live:
            self.phase = str(target.get("phase") or self.phase)
        elif self.weights.get("idle", 0.0) > 0.65:
            self.phase = "idle"
        return {
            "phase": self.phase,
            "palette": self.palette,
            "weights": dict(self.weights),
            "live": self.live,
            "intensity": self.intensity,
            "speed": self.speed,
            "heat": self.heat,
            "st": self.st,
            "mode": self.mode,
            "profile": self.profile,
            "util": self.util,
            "vram": self.vram,
            "temp": self.temp,
            "connected": self.connected,
        }


def scene_from_state(data: dict[str, Any] | None, connected: bool) -> dict[str, Any]:
    data = data or {}
    gpu = data.get("gpu") if isinstance(data.get("gpu"), dict) else {}
    util = _num(gpu.get("utilization_pct"))
    vram = _num(gpu.get("vram_pct"))
    temp = _num(gpu.get("temperature_c"), 40.0)
    kind = str(data.get("kind") or "")
    mode = str(data.get("gpu_mode") or "").strip() or "—"
    profile = str(data.get("profile") or "").strip() or "—"
    restarting = bool(data.get("restarting"))
    switching = bool(data.get("switching") or restarting)
    busy = bool(data.get("busy"))
    working = busy or switching or restarting
    # GPU % only tints the field. nvidia-smi also moves when this kiosk
    # scanouts on the same card, so it must not rename the HUD to generating.
    live = working

    if restarting:
        phase, palette = "restarting", "switch"
    elif switching or (working and kind == "gpu"):
        phase, palette = "switching", "switch"
    elif kind == "image" or mode == "comfy":
        phase, palette = ("rendering" if working else "comfy"), "image"
    elif working and kind == "code":
        phase, palette = "writing code", "chat"
    elif working and kind == "chat":
        phase, palette = "generating", "chat"
    elif working:
        phase, palette = "in use", "chat"
    else:
        phase, palette = "idle", "idle"

    if not connected:
        phase = "waiting for api"

    intensity = 0.24 + 0.52 * (util / 100.0) + 0.16 * (vram / 100.0)
    if not live:
        intensity = min(intensity, 0.42)
    speed = 0.09 if not live else 0.26 + 0.5 * (util / 100.0)
    heat = max(0.0, min(1.0, (temp - 38.0) / 42.0))
    return {
        "phase": phase,
        "palette": palette,
        "live": live,
        "intensity": max(0.16, min(0.98, intensity)),
        "speed": speed,
        "heat": heat,
        "mode": mode,
        "profile": profile,
        "util": util,
        "vram": vram,
        "temp": temp,
        "connected": connected,
    }


class StateBus:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data: dict[str, Any] | None = None
        self.ok = False
        self.stop = threading.Event()

    def snapshot(self) -> tuple[dict[str, Any] | None, bool]:
        with self.lock:
            return self.data, self.ok

    def run(self, url: str, interval: float) -> None:
        while not self.stop.is_set():
            payload = fetch_state(url)
            with self.lock:
                if payload is not None:
                    self.data = payload
                    self.ok = True
            self.stop.wait(interval)


def _warm_palette(
    name: str, heat: float
) -> list[tuple[int, int, int]]:
    base = PALETTES.get(name) or PALETTES["idle"]
    if heat <= 0.02:
        return base
    return [_mix(color, WARN, heat * 0.28 * (i / 255.0)) for i, color in enumerate(base)]


def _blended_palette(weights: dict[str, float], heat: float) -> list[tuple[int, int, int]]:
    names = [name for name, w in weights.items() if w > 0.01 and name in PALETTES]
    if not names:
        names = ["idle"]
    total = sum(weights[name] for name in names) or 1.0
    out: list[tuple[int, int, int]] = []
    for i in range(256):
        r = g = b = 0.0
        for name in names:
            w = weights[name] / total
            cr, cg, cb = PALETTES[name][i]
            r += cr * w
            g += cg * w
            b += cb * w
        color = (int(r), int(g), int(b))
        if heat > 0.02:
            color = _mix(color, WARN, heat * 0.28 * (i / 255.0))
        out.append(color)
    return out


def draw_field(
    width: int,
    height: int,
    scene: dict[str, Any],
) -> Any:
    import pygame

    weights = scene.get("weights")
    if isinstance(weights, dict) and weights:
        mixed = {str(k): float(v) for k, v in weights.items()}
        palette = _blended_palette(mixed, float(scene["heat"]))
    else:
        palette = _warm_palette(str(scene["palette"]), float(scene["heat"]))
    intensity = float(scene["intensity"])
    live = bool(scene["live"])
    st = float(scene.get("st", 0.0))
    breath = 0.5 + 0.5 * lsin(st * (1.15 if live else 0.72))
    gain = intensity * (0.82 + 0.18 * breath)
    cx = (width - 1) * 0.5
    cy = (height - 1) * 0.5
    inv_diag = 1.0 / (math.hypot(cx, cy) + 1.0)
    pulse = (0.22 if live else 0.08) * (0.45 + 0.55 * breath)
    buf = bytearray(width * height * 3)
    i = 0
    for y in range(height):
        for x in range(width):
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx * dx + dy * dy)
            v = (
                lsin(x * 0.041 + st)
                + lsin(y * 0.036 - st * 0.81)
                + lsin((x + y) * 0.021 + st * 1.13)
                + lsin(dist * 0.048 - st * 0.47)
            )
            v = v * 0.25 + 0.5
            v = v * gain + pulse * math.exp(-dist * inv_diag * 3.2)
            if v < 0.0:
                v = 0.0
            elif v > 0.999:
                v = 0.999
            r, g, b = palette[int(v * 255.0)]
            buf[i] = r
            buf[i + 1] = g
            buf[i + 2] = b
            i += 3
    return pygame.image.frombuffer(buf, (width, height), "RGB").convert()


def draw_hud(screen: Any, font, small, scene: dict[str, Any]) -> None:
    w, h = screen.get_size()
    profile = str(scene["profile"])
    mode = str(scene["mode"]).upper()
    phase = str(scene["phase"])
    if scene["connected"]:
        util = int(round(scene["util"]))
        vram = int(round(scene["vram"]))
        temp = int(round(scene["temp"]))
        stats = f"GPU {util}%   VRAM {vram}%   {temp}°C"
    else:
        stats = "no telemetry"
    shadow = (0, 0, 0)

    def blit(text: str, pos: tuple[int, int], color, use_small: bool = False) -> None:
        face = small if use_small else font
        x, y = pos
        img = face.render(text, True, shadow)
        screen.blit(img, (x + 1, y + 1))
        screen.blit(face.render(text, True, color), pos)

    phase_color = WARN if not scene["connected"] else (OK if scene["live"] else MUTED)
    blit(profile, (28, 22), TEXT)
    blit(mode, (w - small.size(mode)[0] - 28, 26), ACCENT, use_small=True)
    blit(phase, (28, h - 52), phase_color)
    blit(stats, (w - small.size(stats)[0] - 28, h - 50), MUTED, use_small=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tabby-stack activity screensaver (KMSDRM)")
    parser.add_argument(
        "--window",
        action="store_true",
        help="Windowed SDL for a machine that already has a GUI (dev only)",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("TABBY_SAVER_URL", "http://127.0.0.1:5000"),
        help="TabbyAPI origin (default TABBY_SAVER_URL or http://127.0.0.1:5000)",
    )
    parser.add_argument("--fps", type=int, default=int(os.environ.get("TABBY_SAVER_FPS", "24")))
    parser.add_argument("--width", type=int, default=256, help="Internal field width")
    parser.add_argument("--height", type=int, default=144, help="Internal field height")
    parser.add_argument("--poll", type=float, default=1.0, help="Seconds between API polls")
    return parser.parse_args(argv)


def _init_display(windowed: bool):
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    if not windowed:
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        os.environ.setdefault("SDL_RENDER_DRIVER", "software")
        os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
        os.environ.pop("DISPLAY", None)
        os.environ.pop("WAYLAND_DISPLAY", None)
    try:
        import pygame
    except ImportError as exc:
        raise SystemExit(
            "tabby-saver: pygame is missing. On Arch: sudo pacman -S --needed python-pygame"
        ) from exc
    pygame.init()
    pygame.mouse.set_visible(False)
    pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN])
    flags = pygame.RESIZABLE if windowed else pygame.FULLSCREEN | pygame.NOFRAME
    size = (1280, 720) if windowed else (0, 0)
    try:
        screen = pygame.display.set_mode(size, flags)
    except pygame.error:
        if windowed:
            raise
        screen = pygame.display.set_mode((1920, 1080), flags)
    pygame.display.set_caption("tabby-stack")
    return pygame, screen


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = saver_url(args.url)
    bus = StateBus()
    thread = threading.Thread(target=bus.run, args=(url, max(0.4, args.poll)), daemon=True)
    thread.start()
    try:
        pygame, screen = _init_display(args.window)
    except Exception as exc:
        bus.stop.set()
        return _drm_fail(exc)

    font = pygame.font.Font(None, 36)
    small = pygame.font.Font(None, 28)
    clock = pygame.time.Clock()
    follow = SceneFollow()
    prev = time.monotonic()
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and args.window:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
            now = time.monotonic()
            dt = now - prev
            prev = now
            data, ok = bus.snapshot()
            scene = follow.tick(scene_from_state(data, ok), dt, now)
            field = draw_field(max(64, args.width), max(36, args.height), scene)
            screen.blit(pygame.transform.smoothscale(field, screen.get_size()), (0, 0))
            draw_hud(screen, font, small, scene)
            pygame.display.flip()
            clock.tick(max(8, min(30, args.fps)))
    finally:
        bus.stop.set()
        pygame.quit()
    return 0


def _drm_fail(exc: BaseException) -> int:
    print(
        "tabby-saver: could not open a KMSDRM display.\n"
        "  Need a free TTY, nvidia-drm.modeset=1, and the video group.\n"
        "  Do not enable this unit if Omarchy or a desktop already owns the GPU.\n"
        f"  {exc}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0) from None

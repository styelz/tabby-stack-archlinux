#!/usr/bin/python
"""CPU-rendered KMSDRM kiosk: stack activity as a thermal field.

Does not import TabbyAPI or CUDA. Polls GET /v1/ui/saver/state on localhost.
Software SDL only — do not point this at a GL renderer on the LLM GPU.
"""

from __future__ import annotations

import argparse
import colorsys
import fcntl
import glob
import json
import math
import os
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
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
DOWN = (48, 10, 14)
DOWN_HOT = (168, 36, 42)
DOWN_TEXT = (232, 96, 90)

VT_ACTIVATE = 0x5606
VT_WAITACTIVE = 0x5607
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03
_GETTY_COMMS = frozenset({"agetty", "getty", "mingetty", "login", "(sd-pam)", "systemd"})
_DISMISS_EVENT_NAMES = (
    "KEYDOWN",
    "KEYUP",
    "MOUSEMOTION",
    "MOUSEBUTTONDOWN",
    "MOUSEBUTTONUP",
    "JOYBUTTONDOWN",
    "JOYAXISMOTION",
    "JOYHATMOTION",
)

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
    "chat": _palette(
        [(0.0, BG), (0.18, (40, 48, 110)), (0.42, ACCENT), (0.68, ACCENT2), (1.0, (255, 96, 140))]
    ),
    "image": _palette([(0.0, BG), (0.38, AMBER_DIM), (1.0, WARN)]),
    "switch": _palette([(0.0, BG), (0.4, GREEN_DIM), (1.0, OK)]),
    "down": _palette([(0.0, (8, 4, 6)), (0.42, DOWN), (1.0, DOWN_HOT)]),
}


def _shift_color(color: tuple[int, int, int], hue_delta: float) -> tuple[int, int, int]:
    """Rotate hue; leave near-black / gray stops so the field still sits on BG."""
    if abs(hue_delta) < 1e-6:
        return color
    r, g, b = color
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if s < 0.08 or v < 0.08:
        return color
    nr, ng, nb = colorsys.hsv_to_rgb((h + hue_delta) % 1.0, s, v)
    return (int(nr * 255.0 + 0.5), int(ng * 255.0 + 0.5), int(nb * 255.0 + 0.5))


def _shift_ramp(
    ramp: list[tuple[int, int, int]], hue_delta: float
) -> list[tuple[int, int, int]]:
    if abs(hue_delta) < 1e-6:
        return ramp
    return [_shift_color(c, hue_delta) for c in ramp]


def _chat_hue_rate(speed: float, token_rate: float, chatty: bool) -> float:
    """Turns of the colour wheel per second. Faster decode / tokens → faster travel."""
    if not chatty:
        return 0.004
    return 0.016 + 0.030 * max(0.0, speed) + min(0.038, max(0.0, token_rate) * 0.0015)


def _fmt_runtime(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


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


def origin_peer(url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return host, int(port)


def tcp_up(host: str, port: int, timeout: float = 0.2) -> bool:
    """True when something is listening. Does not wait on the event loop."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    try:
        sock.close()
    except OSError:
        pass
    return True


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


def _clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def _smoothstep(t: float) -> float:
    t = _clamp01(t)
    return t * t * (3.0 - 2.0 * t)


class SceneFollow:
    """Hold one continuous field: never snap phase, palette, or HUD on a poll."""

    _HOLD_LIVE_S = 0.7
    _BOOT_S = 1.25
    _HALT_S = 5.0
    _TAU_S = 2.4

    def __init__(self) -> None:
        self.intensity = 0.52
        self.speed = 0.34
        self.heat = 0.18
        self.util = 0.0
        self.vram = 0.0
        self.temp = 40.0
        self.st = 0.0
        # Wall-clock seed so a restart is not always the same blue/pink family.
        self.hue = (time.time() * 0.007) % 1.0
        self.live = False
        self._live_until = 0.0
        self.weights = {name: (1.0 if name == "idle" else 0.0) for name in PALETTES}
        self.phase = "idle"
        self.palette = "idle"
        self.mode = "—"
        self.profile = "—"
        self.connected = False
        self.overlay = 0.0
        self.cycle = "idle"
        self.cycle_t = 0.0
        self._cycle_started = 0.0
        self.tokens = 0.0
        self.token_rate = 0.0
        self.stage = "idle"
        self.has_gpu = False
        self.image_n = 0.0
        self.image_of = 0.0
        self.image_file = ""
        self.image_what = ""
        self.note = ""
        self.task_name = ""
        self._task_t0 = 0.0
        self.runtime_s = 0.0

    def _hold_live(self, want: bool, now: float) -> bool:
        if want:
            self._live_until = now + self._HOLD_LIVE_S
            return True
        return now < self._live_until

    def _enter_cycle(self, name: str, now: float, t0: float = 0.0) -> None:
        self.cycle = name
        self.cycle_t = _clamp01(t0)
        if name == "boot":
            self._cycle_started = now - self.cycle_t * self._BOOT_S
        elif name == "halt":
            self._cycle_started = now - self.cycle_t * self._HALT_S
        else:
            self._cycle_started = now

    def _tick_cycle(self, held: bool, now: float) -> None:
        if held:
            if self.cycle == "idle":
                self._enter_cycle("boot", now)
            elif self.cycle == "halt":
                self._enter_cycle("boot", now, t0=max(0.0, 1.0 - self.cycle_t))
            if self.cycle == "boot":
                self.cycle_t = min(1.0, (now - self._cycle_started) / self._BOOT_S)
                if self.cycle_t >= 1.0:
                    self._enter_cycle("run", now)
                    self.cycle_t = 1.0
            elif self.cycle == "run":
                self.cycle_t = 1.0
            return
        if self.cycle in ("boot", "run"):
            t0 = 0.0 if self.cycle == "run" else max(0.0, 1.0 - self.cycle_t)
            self._enter_cycle("halt", now, t0=t0)
        if self.cycle == "halt":
            self.cycle_t = min(1.0, (now - self._cycle_started) / self._HALT_S)
            if self.cycle_t >= 1.0:
                self._enter_cycle("idle", now)
                self.cycle_t = 0.0

    def tick(self, target: dict[str, Any], dt: float, now: float) -> dict[str, Any]:
        dt = 0.0 if dt < 0.0 else 0.08 if dt > 0.08 else dt
        want_live = bool(target.get("live"))
        held = self._hold_live(want_live, now)
        self.live = held
        self._tick_cycle(held, now)
        if self.cycle == "boot":
            # Neurons must read as live on the first busy poll. The bloom still
            # uses cycle_t; do not fade the overlay in over a second.
            self.overlay = 1.0
        elif self.cycle == "run":
            self.overlay = 1.0
        elif self.cycle == "halt":
            # Linear over _HALT_S so they dim the whole way instead of snapping off.
            self.overlay = 1.0 - self.cycle_t
        else:
            self.overlay = 0.0
        if self.cycle != "halt" and self.overlay < 0.002:
            self.overlay = 0.0
        tau = 0.45 if (want_live or held) else 2.2
        self.intensity = _exp_approach(self.intensity, float(target["intensity"]), dt, tau)
        self.speed = _exp_approach(self.speed, float(target["speed"]), dt, tau)
        self.heat = _exp_approach(self.heat, float(target["heat"]), dt, tau)
        self.util = _exp_approach(self.util, float(target["util"]), dt, 1.6)
        self.vram = _exp_approach(self.vram, float(target["vram"]), dt, 1.6)
        self.temp = _exp_approach(
            self.temp, float(target["temp"]), dt, 0.55 if (want_live or held) else 1.6
        )
        self.st += self.speed * dt
        dest = str(target.get("palette") or "idle")
        if dest not in self.weights:
            dest = "idle"
        down = dest == "down" or not bool(target.get("connected"))
        if dest == "down":
            for name in self.weights:
                self.weights[name] = 1.0 if name == dest else 0.0
        else:
            blend_tau = 0.12 if (want_live or held) else 1.8
            for name in self.weights:
                goal = 1.0 if name == dest else 0.0
                self.weights[name] = _exp_approach(self.weights[name], goal, dt, blend_tau)
        self.palette = max(self.weights, key=lambda name: self.weights[name])
        self.mode = str(target.get("mode") or self.mode)
        self.profile = str(target.get("profile") or self.profile)
        self.connected = bool(target.get("connected"))
        dest_tokens = max(0.0, float(target.get("tokens") or 0.0))
        if dest_tokens + 1.0 < self.tokens:
            self.tokens = dest_tokens
            self.token_rate = 0.0
        else:
            delta = max(0.0, dest_tokens - self.tokens)
            inst = min(80.0, delta / dt) if dt > 1e-6 else 0.0
            self.token_rate = _exp_approach(self.token_rate, inst, dt, 0.22)
            self.tokens = dest_tokens
        chatty = dest == "chat" or self.weights.get("chat", 0.0) > 0.18
        self.hue = (self.hue + _chat_hue_rate(self.speed, self.token_rate, chatty) * dt) % 1.0
        self.stage = str(target.get("stage") or self.stage or "idle")
        self.has_gpu = bool(target.get("has_gpu"))
        self.image_n = _exp_approach(
            self.image_n, float(target.get("image_n") or 0.0), dt, 0.4
        )
        self.image_of = float(target.get("image_of") or 0.0)
        dest_file = str(target.get("image_file") or "").strip()
        dest_what = str(target.get("image_what") or "").strip()
        if dest_file:
            self.image_file = dest_file
        if dest_what:
            self.image_what = dest_what
        if self.cycle == "idle" and not held:
            self.image_file = dest_file
            self.image_what = dest_what
        self.note = str(target.get("note") or "")
        if not self.connected or dest == "down":
            self.phase = str(target.get("phase") or "restarting api")
        elif self.cycle == "boot":
            self.phase = "imagining"
        elif self.cycle == "halt":
            self.phase = "dreaming"
        elif held:
            self.phase = str(target.get("phase") or self.phase)
        elif self.weights.get("idle", 0.0) > 0.65:
            self.phase = "idle"
        if self.phase != self.task_name:
            self.task_name = self.phase
            self._task_t0 = now
        self.runtime_s = max(0.0, now - self._task_t0) if self._task_t0 else 0.0
        show_clock = self.phase not in {"idle"} or dest == "down"
        runtime = _fmt_runtime(self.runtime_s) if show_clock else ""
        return {
            "phase": self.phase,
            "palette": self.palette,
            "weights": dict(self.weights),
            "live": self.live,
            "intensity": self.intensity,
            "speed": self.speed,
            "heat": self.heat,
            "st": self.st,
            "hue": self.hue,
            "mode": self.mode,
            "profile": self.profile,
            "util": self.util,
            "vram": self.vram,
            "temp": self.temp,
            "connected": self.connected,
            "overlay": self.overlay,
            "cycle": self.cycle,
            "cycle_t": self.cycle_t,
            "tokens": self.tokens,
            "token_rate": self.token_rate,
            "stage": self.stage,
            "has_gpu": self.has_gpu,
            "image_n": self.image_n,
            "image_of": self.image_of,
            "image_file": self.image_file,
            "image_what": self.image_what,
            "note": self.note,
            "runtime": runtime,
            "runtime_s": self.runtime_s,
        }


def scene_from_state(data: dict[str, Any] | None, connected: bool) -> dict[str, Any]:
    data = data or {}
    gpu = data.get("gpu") if isinstance(data.get("gpu"), dict) else {}
    util_raw = gpu.get("utilization_pct")
    vram_raw = gpu.get("vram_pct")
    temp_raw = gpu.get("temperature_c")
    has_gpu = any(value is not None and value != "" for value in (util_raw, vram_raw, temp_raw))
    util = _num(util_raw) if util_raw is not None else 0.0
    vram = _num(vram_raw) if vram_raw is not None else 0.0
    temp = _num(temp_raw, 40.0) if temp_raw is not None else 40.0
    kind = str(data.get("kind") or "")
    mode = str(data.get("gpu_mode") or "").strip() or "—"
    profile = str(data.get("profile") or "").strip() or "—"
    restarting = bool(data.get("restarting"))
    switching = bool(data.get("switching") or restarting)
    busy = bool(data.get("busy"))
    stage = str(data.get("stage") or "").strip().lower()
    working = busy or switching or restarting or stage in {"prefill", "decode", "tool"}
    tokens = max(0.0, _num(data.get("tokens")))
    image_n = _num(data.get("image_n")) if data.get("image_n") is not None else 0.0
    image_of = _num(data.get("image_of")) if data.get("image_of") is not None else 0.0
    # GPU % only tints the field. nvidia-smi also moves when this kiosk
    # scanouts on the same card, so it must not rename the HUD to generating.
    live = working or stage in {"prefill", "decode", "tool"}

    image_job = kind == "image" or mode == "comfy" or stage == "image"
    down = (not connected) or restarting
    note = ""
    if down:
        if restarting and connected:
            phase, palette = "restarting api", "down"
            note = "reloading python / weights"
        elif data:
            phase, palette = "restarting api", "down"
            note = "waiting for /health"
        else:
            phase, palette = "waiting for api", "down"
            note = "waiting for /health"
        live = True
        intensity = 0.30
        speed = 0.20
        heat = 0.42
    elif stage == "switch" or switching or (working and kind == "gpu"):
        if image_job:
            phase, palette = "reloading", "switch"
        else:
            phase, palette = "switching", "switch"
    elif image_job:
        phase, palette = ("rendering" if working else "comfy"), "image"
    elif working and kind == "code":
        phase, palette = ("using tools" if stage == "tool" else "writing code"), "chat"
    elif working and stage == "tool":
        phase, palette = "using tools", "chat"
    elif working and kind == "chat" and stage == "prefill":
        phase, palette = "thinking", "chat"
    elif working and kind == "chat":
        phase, palette = "thinking", "chat"
    elif working and stage == "prefill":
        phase, palette = "thinking", "chat"
    elif working and stage == "decode":
        phase, palette = "thinking", "chat"
    elif working:
        phase, palette = "in use", "chat"
    else:
        phase, palette = "idle", "idle"

    if down:
        pass
    elif not live:
        # Idle still has to drift: a nearly-static navy field reads as frozen.
        intensity = min(0.52 + 0.18 * (vram / 100.0), 0.70)
        speed = 0.36 + 0.10 * (vram / 100.0)
        heat = max(0.10, min(0.38, 0.12 + (temp - 38.0) / 90.0))
    elif stage == "prefill":
        intensity = 0.70 + 0.12 * (util / 100.0)
        speed = 0.42 + 0.16 * (util / 100.0)
        heat = max(0.28, min(0.85, 0.32 + (temp - 38.0) / 50.0))
    elif stage == "tool":
        intensity = 0.60
        speed = 0.38
        heat = max(0.22, min(0.70, 0.28 + (temp - 38.0) / 55.0))
    elif stage == "image":
        frac = (image_n / image_of) if image_of > 0 else 0.45
        intensity = 0.72 + 0.18 * frac
        speed = 0.48 + 0.22 * frac
        heat = max(0.35, min(1.0, 0.45 + (temp - 38.0) / 42.0))
    else:
        # Job running: ignore nvidia-smi (often near 0 during decode).
        intensity = 0.78 + 0.20 * (util / 100.0)
        speed = 0.55 + 0.35 * (util / 100.0)
        heat = max(0.35, min(1.0, 0.45 + (temp - 38.0) / 42.0))
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
        "has_gpu": has_gpu,
        "tokens": tokens,
        "stage": stage or ("idle" if not live else "decode"),
        "image_n": image_n,
        "image_of": image_of,
        "image_file": str(data.get("image_file") or "").strip(),
        "image_what": str(data.get("image_what") or "").strip(),
        "note": note,
        "waiters": _num(data.get("waiters")),
        "elapsed_s": _num(data.get("elapsed_s")),
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

    def ingest(self, payload: dict[str, Any] | None, reachable: bool) -> None:
        """HTTP JSON vs TCP. A hung generate times out but keeps the port open."""
        with self.lock:
            if payload is not None:
                self.data = payload
                self.ok = True
                return
            if not reachable:
                self.ok = False
                return
            if self.data is None:
                self.ok = False

    def run(self, url: str, interval: float) -> None:
        host, port = origin_peer(url)
        while not self.stop.is_set():
            reachable = tcp_up(host, port)
            payload = fetch_state(url) if reachable else None
            if payload is None:
                reachable = tcp_up(host, port)
            self.ingest(payload, reachable)
            self.stop.wait(interval)


def _warm_palette(
    name: str, heat: float, hue: float = 0.0
) -> list[tuple[int, int, int]]:
    base = PALETTES.get(name) or PALETTES["idle"]
    if name == "chat":
        base = _shift_ramp(base, hue)
    if name == "down" or heat <= 0.02:
        return base
    return [_mix(color, WARN, heat * 0.28 * (i / 255.0)) for i, color in enumerate(base)]


def _u01(i: int, salt: int = 0) -> float:
    x = (i * 374761393 + salt * 668265263) & 0xFFFFFFFF
    x = (x ^ (x >> 13)) * 1274126177 & 0xFFFFFFFF
    return (x & 0xFFFFFF) / float(0xFFFFFF)


def _ramp_color(ramp: list[tuple[int, int, int]], t: float) -> tuple[int, int, int]:
    if not ramp:
        return ACCENT
    t = _clamp01(t)
    if len(ramp) == 1:
        return ramp[0]
    span = (len(ramp) - 1) * t
    idx = int(span)
    if idx >= len(ramp) - 1:
        return ramp[-1]
    return _mix(ramp[idx], ramp[idx + 1], span - idx)


def _neuron_rest(n: int = 58) -> list[tuple[float, float]]:
    """First-added scatter: golden-ratio tissue stretched to the bezel."""
    golden = 0.5 * (1.0 + math.sqrt(5.0))
    raw_x = [(i * golden) % 1.0 for i in range(n)]
    raw_y = [(i + 0.5) / n for i in range(n)]
    minx, maxx = min(raw_x), max(raw_x)
    miny, maxy = min(raw_y), max(raw_y)
    pts: list[tuple[float, float]] = []
    for x, y in zip(raw_x, raw_y):
        nx = 0.0 if maxx == minx else (x - minx) / (maxx - minx)
        ny = 0.0 if maxy == miny else (y - miny) / (maxy - miny)
        pts.append((nx, ny))
    return pts


def _neuron_edges(pts: list[tuple[float, float]]) -> list[tuple[int, int]]:
    n = len(pts)
    seen: set[tuple[int, int]] = set()
    edges: list[tuple[int, int]] = []

    def add(i: int, j: int) -> None:
        if i == j:
            return
        a, b = (i, j) if i < j else (j, i)
        if (a, b) in seen:
            return
        seen.add((a, b))
        edges.append((a, b))

    for i in range(n):
        p = pts[i]
        near = sorted(
            (math.hypot(p[0] - pts[j][0], p[1] - pts[j][1]), j) for j in range(n) if j != i
        )
        for _dist, j in near[:3]:
            add(i, j)
    for i in range(0, n, 7):
        add(i, (i + n // 3) % n)
    return edges


NEURON_REST = _neuron_rest()
NEURON_EDGES = _neuron_edges(NEURON_REST)
NEURON_SPARK = {
    "idle": ((90, 130, 210), (210, 230, 255)),
    "chat": ((90, 160, 255), (255, 210, 240)),
    "image": ((180, 110, 40), (255, 220, 120)),
    "switch": ((40, 160, 110), (180, 255, 210)),
    "down": ((140, 28, 36), (255, 92, 78)),
}
NEURON_RAMPS: dict[str, list[tuple[int, int, int]]] = {
    "idle": [(90, 130, 210), (140, 175, 235), (190, 215, 250), (220, 235, 255)],
    "chat": [(40, 220, 255), (80, 150, 255), (139, 92, 246), (220, 70, 210), (255, 90, 170)],
    "image": [(255, 196, 64), (255, 140, 48), (255, 88, 72), (255, 110, 160), (255, 190, 140)],
    "switch": [(20, 200, 190), (48, 230, 130), (140, 255, 170), (200, 255, 210)],
    "down": [(80, 16, 20), (140, 28, 36), (200, 48, 48), (255, 96, 80)],
}
# GPU °C outline: gold → ember → red-orange → white-hot.
HOT_GLOW = [(255, 210, 96), (255, 158, 48), (255, 86, 32), (255, 236, 210)]
# Real envelope from Status metrics on this 4070 Ti: idle 37–44°C,
# busy 50–68°C (never the 80–90°C the first scale assumed).
_TEMP_GLOW_LO = 44.0
_TEMP_GLOW_HI = 68.0


def _temp_hotness(temp: float) -> float:
    """Linear 0 at idle-cluster top, 1 at the hottest samples this card hits."""
    span = _TEMP_GLOW_HI - _TEMP_GLOW_LO
    if span <= 0.0:
        return 0.0
    return _clamp01((float(temp) - _TEMP_GLOW_LO) / span)


def overlay_amount(scene: dict[str, Any]) -> float:
    raw = scene.get("overlay")
    if raw is None:
        return 1.0 if scene.get("live") else 0.0
    try:
        return _clamp01(float(raw))
    except (TypeError, ValueError):
        return 0.0


def neuron_overlay_state(scene: dict[str, Any]) -> dict[str, Any] | None:
    """Unit-space graph + fires. None when the overlay has fully faded."""
    overlay = overlay_amount(scene)
    cycle = str(scene.get("cycle") or "")
    if overlay <= 0.02:
        return None
    st = float(scene.get("st", 0.0))
    intensity = float(scene.get("intensity") or 0.0)
    stage = str(scene.get("stage") or "")
    token_rate = float(scene.get("token_rate") or 0.0)
    tokens = int(float(scene.get("tokens") or 0.0))
    image_n = float(scene.get("image_n") or 0.0)
    image_of = float(scene.get("image_of") or 0.0)
    if cycle == "boot" and overlay < 0.08:
        overlay = 0.08
    nodes: list[tuple[float, float]] = []
    fires: list[float] = []
    for i, (nx, ny) in enumerate(NEURON_REST):
        nodes.append(
            (
                _clamp01(nx + 0.018 * lsin(st * 0.33 + i * 0.37)),
                _clamp01(ny + 0.016 * lsin(st * 0.27 + i * 0.51)),
            )
        )
        rest = 0.10 + 0.10 * (0.5 + 0.5 * lsin(st * 2.3 + i * 0.91))
        pop = 0.5 + 0.5 * lsin(st * (4.1 + 0.13 * (i % 8)) + i * 1.27)
        thresh = 0.84 - 0.14 * intensity
        if stage == "prefill":
            thresh = 0.70 - 0.10 * intensity
        elif stage == "tool":
            thresh = 0.92
        spike = 0.0
        if pop > thresh:
            spike = min(1.0, (pop - thresh) / max(0.04, 1.0 - thresh))
        fire = max(rest, spike) * overlay
        if stage == "decode" and token_rate > 0.5:
            boost = min(1.0, token_rate / 18.0)
            pick = _u01(i, tokens * 17 + 3)
            if pick < 0.22 + 0.35 * boost:
                fire = max(fire, (0.55 + 0.45 * boost) * overlay)
        fires.append(fire)
    pulses: list[tuple[int, float, float]] = []
    if stage == "prefill":
        rate = 0.32 + 0.45 * intensity
        extra = 1
    elif stage == "tool":
        rate = 0.22 + 0.20 * intensity
        extra = 1
    elif stage == "image":
        frac = (image_n / image_of) if image_of > 0 else 0.4
        rate = 0.40 + 0.70 * frac
        extra = 1 + (1 if frac > 0.5 else 0)
    else:
        boost = min(1.6, 0.15 * token_rate)
        rate = 0.70 + 1.25 * intensity + boost
        extra = 1 + (1 if intensity > 0.72 or token_rate > 8 else 0)
        extra += 1 if intensity > 0.90 or token_rate > 20 else 0
    reverse = cycle == "halt"
    for ei, (a, b) in enumerate(NEURON_EDGES):
        for p in range(extra):
            phase = (st * rate * (0.50 + 0.85 * _u01(ei, p + 3)) + _u01(ei, p + 17)) % 1.0
            if reverse:
                phase = 1.0 - phase
            u = phase * 2.0
            if u > 1.0:
                u = 2.0 - u
            bright = (0.45 + 0.55 * intensity) * overlay
            pulses.append((ei, u, bright))
            width = 0.16
            if u < width:
                fires[a] = max(fires[a], (1.0 - u / width) * overlay)
            if u > 1.0 - width:
                fires[b] = max(fires[b], ((u - (1.0 - width)) / width) * overlay)
    return {
        "nodes": nodes,
        "edges": NEURON_EDGES,
        "fires": fires,
        "pulses": pulses,
        "overlay": overlay,
        "reverse": reverse,
    }


def _draw_glow(
    pygame_mod: Any,
    screen: Any,
    pos: tuple[int, int],
    color: tuple[int, int, int],
    strength: float,
    scale: float = 1.0,
) -> None:
    if strength <= 0.02:
        return
    for rad, amt in ((9.0, 0.12), (5.0, 0.28), (2.0, 0.55)):
        r = max(1, int(round(rad * scale * (0.55 + 0.45 * strength))))
        pygame_mod.draw.circle(screen, _mix(BG, color, amt * strength), pos, r)


def neuron_draw_sizes(
    fire: float, bright: float, height: float = 1080.0, fade: float = 1.0
) -> tuple[int, int]:
    """Soma and pulse radii. About half the first-added thickness."""
    h = max(1.0, float(height))
    fade = _clamp01(fade)
    ring = int(round((h / 380.0) * (1.5 + 3.5 * fire) * fade))
    head = int(round((h / 420.0) * (1.1 + 1.4 * bright) * fade))
    return ring, head


def draw_neurons(pygame_mod: Any, screen: Any, scene: dict[str, Any]) -> None:
    state = neuron_overlay_state(scene)
    if state is None:
        return
    w, h = screen.get_size()
    overlay = float(state["overlay"])
    name = str(scene.get("palette") or "chat")
    axon, spark = NEURON_SPARK.get(name) or NEURON_SPARK["chat"]
    if name == "chat":
        hue = float(scene.get("hue") or 0.0)
        axon = _shift_color(axon, hue)
        spark = _shift_color(spark, hue)
    hotness = _temp_hotness(float(scene.get("temp") or 0.0)) if scene.get("has_gpu") else 0.0
    hot = _ramp_color(HOT_GLOW, hotness)
    dim_axon = _mix(BG, axon, 0.42 * overlay)
    last_x = max(1, w - 1)
    last_y = max(1, h - 1)
    nodes = [(int(round(x * last_x)), int(round(y * last_y))) for x, y in state["nodes"]]
    edges: list[tuple[int, int]] = state["edges"]
    if overlay > 0.04:
        for a, b in edges:
            if nodes[a] != nodes[b]:
                pygame_mod.draw.line(screen, dim_axon, nodes[a], nodes[b], 1)
    for ei, u, bright in state["pulses"]:
        a, b = edges[ei]
        x0, y0 = nodes[a]
        x1, y1 = nodes[b]
        px = int(x0 + (x1 - x0) * u)
        py = int(y0 + (y1 - y0) * u)
        _ring, head = neuron_draw_sizes(0.0, bright, h, overlay)
        if head < 1:
            continue
        color = _mix(BG, _mix(axon, spark, bright), overlay)
        pygame_mod.draw.circle(screen, color, (px, py), head)
        if overlay > 0.45 and head > 1:
            pygame_mod.draw.circle(screen, _mix(BG, (255, 255, 255), overlay), (px, py), max(1, head // 2))
    fires: list[float] = state["fires"]
    for i, (x, y) in enumerate(nodes):
        fire = fires[i]
        ring, _head = neuron_draw_sizes(fire, 0.0, h, overlay)
        if hotness > 0.05 and overlay > 0.08:
            halo = overlay * hotness * (0.30 + 0.70 * max(fire, 0.22))
            soma_r = max(ring, int(round((h / 380.0) * 1.5 * overlay)))
            if halo > 0.02 and soma_r >= 1:
                _draw_glow(
                    pygame_mod,
                    screen,
                    (x, y),
                    hot,
                    halo,
                    scale=1.05 + 1.7 * hotness + 0.45 * fire,
                )
                outline_r = max(soma_r + 2, int(round(soma_r * (1.35 + 0.55 * hotness))))
                width = max(1, int(round(1.0 + 2.4 * hotness)))
                pygame_mod.draw.circle(
                    screen,
                    _mix(BG, hot, overlay * (0.38 + 0.52 * hotness)),
                    (x, y),
                    outline_r,
                    width,
                )
        if ring < 1:
            continue
        body = _mix(axon, spark, fire)
        amt = overlay * (0.40 + 0.60 * fire)
        if amt <= 0.03:
            continue
        pygame_mod.draw.circle(screen, _mix(BG, body, amt * 0.55), (x, y), ring + 1)
        pygame_mod.draw.circle(screen, _mix(BG, body, amt), (x, y), ring)
        if fire > 0.35 and overlay > 0.45 and ring > 1:
            pygame_mod.draw.circle(
                screen, _mix(BG, (255, 255, 255), overlay), (x, y), max(1, ring // 3)
            )


def draw_cycle_fx(pygame_mod: Any, screen: Any, scene: dict[str, Any]) -> None:
    """Center bloom + ring: imagining expands, dreaming contracts. Field stays on."""
    cycle = str(scene.get("cycle") or "")
    if cycle not in ("boot", "halt"):
        return
    try:
        t = _clamp01(float(scene.get("cycle_t") or 0.0))
    except (TypeError, ValueError):
        t = 0.0
    w, h = screen.get_size()
    cx, cy = w // 2, h // 2
    name = str(scene.get("palette") or "chat")
    ramp = NEURON_RAMPS.get(name) or NEURON_RAMPS["chat"]
    if name == "chat":
        ramp = _shift_ramp(ramp, float(scene.get("hue") or 0.0))
    color = _ramp_color(ramp, 0.45 if cycle == "boot" else 0.2)
    span = min(w, h)
    if cycle == "boot":
        core = max(0.0, 1.0 - t * 1.15)
        radius = max(10, int(span * 0.06 + span * 0.42 * t))
        _draw_glow(pygame_mod, screen, (cx, cy), color, 0.50 + 0.50 * core, scale=2.2 + 3.6 * core)
        pygame_mod.draw.circle(screen, _mix(BG, color, 0.22 + 0.38 * core), (cx, cy), max(4, int(18 * core)))
    else:
        core = max(0.0, 1.0 - t)
        radius = max(8, int(span * 0.48 * core))
        _draw_glow(pygame_mod, screen, (cx, cy), color, 0.28 + 0.40 * core, scale=1.6 + 2.2 * core)
    if radius > 6:
        ring = _mix(BG, color, 0.40 if cycle == "boot" else 0.28)
        pygame_mod.draw.circle(screen, ring, (cx, cy), radius, 2)
        inner = max(1, radius - 6)
        if inner < radius:
            pygame_mod.draw.circle(screen, _mix(BG, color, 0.18), (cx, cy), inner, 1)


# Idle-only: faint geometric outlines on staggered cadences.
# At idle speed ~0.36 that is roughly 25–55s between appearances, ~6s visible.
_SLEEP_ACTORS = (
    ("diamond", 8.6, 0.15, 0.20, 0.42, 1.00),
    ("zzz", 11.4, 0.62, 0.72, 0.30, 0.85),
    ("hex", 14.1, 0.33, 0.58, 0.66, 0.92),
    ("ring", 17.5, 0.08, 0.84, 0.20, 1.10),
    ("tri", 9.8, 0.81, 0.38, 0.76, 0.88),
    ("diamond", 19.2, 0.47, 0.12, 0.58, 0.78),
)
_SLEEP_LIFE = 0.24
_SLEEP_LO = (72, 90, 132)
_SLEEP_HI = (176, 196, 236)


def idle_sleeper_items(scene: dict[str, Any], width: int, height: int) -> list[dict[str, Any]]:
    """Unit sprites that fade in while the field is fully idle. Empty otherwise."""
    if overlay_amount(scene) > 0.04:
        return []
    if str(scene.get("cycle") or "idle") != "idle":
        return []
    if scene.get("live"):
        return []
    if str(scene.get("palette") or "") == "down" or not scene.get("connected", True):
        return []
    st = float(scene.get("st") or 0.0)
    hue = float(scene.get("hue") or 0.0)
    w = max(1, int(width))
    h = max(1, int(height))
    out: list[dict[str, Any]] = []
    for i, (kind, period, phase, x0, y0, scale) in enumerate(_SLEEP_ACTORS):
        period = max(1.0, float(period))
        u = (st / period + phase + hue) % 1.0
        if u > _SLEEP_LIFE:
            continue
        fade = _smoothstep(u / 0.06) * _smoothstep((_SLEEP_LIFE - u) / 0.07)
        if fade <= 0.02:
            continue
        drift = u / _SLEEP_LIFE
        x = x0 + 0.035 * lsin(st * 0.41 + i * 1.7)
        y = y0 + 0.025 * lsin(st * 0.33 + i * 2.1) - 0.055 * drift
        x = 0.06 if x < 0.06 else 0.94 if x > 0.94 else x
        y = 0.08 if y < 0.08 else 0.90 if y > 0.90 else y
        out.append(
            {
                "kind": kind,
                "x": int(round(x * (w - 1))),
                "y": int(round(y * (h - 1))),
                "size": max(18, int(round(h * 0.050 * scale))),
                "amt": fade,
                "flip": _u01(i + 3, int(hue * 97) + i) > 0.5,
            }
        )
    return out


def _sleep_ink(amt: float) -> tuple[int, int, int]:
    """Stay in idle navy-blue. Never mix toward black or the field will stamp."""
    return _mix(_SLEEP_LO, _SLEEP_HI, 0.22 + 0.55 * _clamp01(amt))


def _sleep_thick(size: int) -> int:
    return 1 if size < 36 else 2


def _draw_z_glyph(
    pygame_mod: Any,
    screen: Any,
    x: int,
    y: int,
    size: int,
    color: tuple[int, int, int],
    thick: int = 1,
) -> None:
    s = max(4, int(size))
    t = max(1, int(thick))
    pygame_mod.draw.line(screen, color, (x, y), (x + s, y), t)
    pygame_mod.draw.line(screen, color, (x + s, y), (x, y + s), t)
    pygame_mod.draw.line(screen, color, (x, y + s), (x + s, y + s), t)


def _outline_poly(
    pygame_mod: Any,
    screen: Any,
    pts: list[tuple[int, int]],
    color: tuple[int, int, int],
    width: int,
) -> None:
    if len(pts) < 3:
        return
    pygame_mod.draw.polygon(screen, color, pts, max(1, width))


def _draw_sleeping_diamond(
    pygame_mod: Any, screen: Any, cx: int, cy: int, size: int, amt: float, flip: bool
) -> None:
    ink = _sleep_ink(amt)
    w = _sleep_thick(size)
    rx = max(8, int(size * 0.72))
    ry = max(7, int(size * 0.58))
    if flip:
        rx, ry = ry, rx
    pts = [(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)]
    _outline_poly(pygame_mod, screen, pts, ink, w)
    zs = max(5, size // 5)
    _draw_z_glyph(pygame_mod, screen, cx + rx + 2, cy - ry - zs, zs, ink, 1)


def _draw_sleeping_hex(
    pygame_mod: Any, screen: Any, cx: int, cy: int, size: int, amt: float, flip: bool
) -> None:
    ink = _sleep_ink(amt)
    w = _sleep_thick(size)
    r = max(8, int(size * 0.70))
    twist = 0.52 if flip else 0.0
    pts = []
    for i in range(6):
        a = twist + i * (math.pi / 3.0)
        pts.append((int(round(cx + r * math.cos(a))), int(round(cy + r * math.sin(a)))))
    _outline_poly(pygame_mod, screen, pts, ink, w)


def _draw_sleeping_tri(
    pygame_mod: Any, screen: Any, cx: int, cy: int, size: int, amt: float, flip: bool
) -> None:
    ink = _sleep_ink(amt)
    w = _sleep_thick(size)
    h = max(8, int(size * 0.78))
    b = max(8, int(size * 0.82))
    if flip:
        pts = [(cx, cy + h), (cx + b, cy - h // 2), (cx - b, cy - h // 2)]
    else:
        pts = [(cx, cy - h), (cx + b, cy + h // 2), (cx - b, cy + h // 2)]
    _outline_poly(pygame_mod, screen, pts, ink, w)


def _draw_sleeping_zzz(
    pygame_mod: Any, screen: Any, cx: int, cy: int, size: int, amt: float
) -> None:
    ink = _sleep_ink(amt)
    s0 = max(6, int(size * 0.42))
    _draw_z_glyph(pygame_mod, screen, cx - s0, cy + s0 // 4, s0, ink, 1)
    s1 = max(7, int(size * 0.58))
    _draw_z_glyph(pygame_mod, screen, cx, cy - s1 // 5, s1, ink, 1)
    s2 = max(8, int(size * 0.74))
    _draw_z_glyph(pygame_mod, screen, cx + s1 // 2, cy - s2, s2, ink, 1)


def _draw_sleeping_ring(
    pygame_mod: Any, screen: Any, cx: int, cy: int, size: int, amt: float
) -> None:
    ink = _sleep_ink(amt)
    w = _sleep_thick(size)
    r = max(8, int(size * 0.70))
    pygame_mod.draw.circle(screen, ink, (cx, cy), r, w)
    inner = max(3, r // 2)
    if inner + w < r:
        pygame_mod.draw.circle(screen, ink, (cx, cy), inner, 1)


def draw_sleepers(pygame_mod: Any, screen: Any, scene: dict[str, Any]) -> None:
    w, h = screen.get_size()
    for item in idle_sleeper_items(scene, w, h):
        kind = item["kind"]
        x, y, size, amt = item["x"], item["y"], item["size"], item["amt"]
        if kind == "hex":
            _draw_sleeping_hex(pygame_mod, screen, x, y, size, amt, item["flip"])
        elif kind == "tri":
            _draw_sleeping_tri(pygame_mod, screen, x, y, size, amt, item["flip"])
        elif kind == "ring":
            _draw_sleeping_ring(pygame_mod, screen, x, y, size, amt)
        elif kind == "zzz":
            _draw_sleeping_zzz(pygame_mod, screen, x, y, size, amt)
        else:
            _draw_sleeping_diamond(pygame_mod, screen, x, y, size, amt, item["flip"])


def _blended_palette(
    weights: dict[str, float], heat: float, hue: float = 0.0
) -> list[tuple[int, int, int]]:
    names = [name for name, w in weights.items() if w > 0.01 and name in PALETTES]
    if not names:
        names = ["idle"]
    total = sum(weights[name] for name in names) or 1.0
    ramps = {
        name: (_shift_ramp(PALETTES[name], hue) if name == "chat" else PALETTES[name])
        for name in names
    }
    out: list[tuple[int, int, int]] = []
    for i in range(256):
        r = g = b = 0.0
        for name in names:
            w = weights[name] / total
            cr, cg, cb = ramps[name][i]
            r += cr * w
            g += cg * w
            b += cb * w
        color = (int(r), int(g), int(b))
        down_w = weights.get("down", 0.0) / total
        if down_w > 0.45:
            pass
        elif heat > 0.02:
            color = _mix(color, WARN, heat * 0.28 * (i / 255.0))
        out.append(color)
    return out


def _field_common(width: int, height: int, scene: dict[str, Any]):
    hue = float(scene.get("hue") or 0.0)
    weights = scene.get("weights")
    if isinstance(weights, dict) and weights:
        mixed = {str(k): float(v) for k, v in weights.items()}
        palette = _blended_palette(mixed, float(scene["heat"]), hue)
    else:
        palette = _warm_palette(str(scene["palette"]), float(scene["heat"]), hue)
    intensity = float(scene["intensity"])
    mix = overlay_amount(scene)
    st = float(scene.get("st", 0.0))
    breath_idle = 0.5 + 0.5 * lsin(st * 1.55)
    breath_live = 0.5 + 0.5 * lsin(st * 1.15)
    breath = breath_idle + (breath_live - breath_idle) * mix
    gain = intensity * (0.82 + 0.18 * breath)
    cx = (width - 1) * 0.5
    cy = (height - 1) * 0.5
    inv_diag = 1.0 / (math.hypot(cx, cy) + 1.0)
    pulse = (0.22 + 0.06 * mix) * (0.45 + 0.55 * breath)
    ax = cx + lsin(st * 0.62) * cx * 0.38
    ay = cy + lsin(st * 0.47 + 1.2) * cy * 0.32
    bx = cx + lsin(st * 0.31 + 2.1) * cx * 0.45
    by = cy + lsin(st * 0.53 + 0.4) * cy * 0.40
    return palette, mix, st, gain, cx, cy, inv_diag, pulse, ax, ay, bx, by


def _draw_field_numpy(width: int, height: int, scene: dict[str, Any], np_mod: Any) -> Any:
    import pygame

    palette, mix, st, gain, cx, cy, inv_diag, pulse, ax, ay, bx, by = _field_common(
        width, height, scene
    )
    pal = np_mod.asarray(palette, dtype=np_mod.uint8)
    lut = np_mod.asarray(SIN_LUT, dtype=np_mod.float32)
    scale = np_mod.float32(SIN_SIZE / TWO_PI)

    def vsin(arr: Any) -> Any:
        idx = (arr * scale).astype(np_mod.int32) & SIN_MASK
        return lut[idx]

    xs = np_mod.arange(width, dtype=np_mod.float32)
    ys = np_mod.arange(height, dtype=np_mod.float32)
    x, y = np_mod.meshgrid(xs, ys)
    dist = np_mod.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    glow = pulse * np_mod.exp(-dist * inv_diag * 3.2)
    use_idle = mix <= 0.02
    use_live = mix >= 0.98
    v_idle = None
    v_live = None
    if not use_live:
        da = np_mod.sqrt((x - ax) ** 2 + (y - ay) ** 2)
        db = np_mod.sqrt((x - bx) ** 2 + (y - by) ** 2)
        wave = (
            vsin(x * 0.048 + st * 1.35)
            + vsin(y * 0.042 - st * 1.18)
            + vsin((x + y) * 0.028 + st * 0.92)
            + vsin(dist * 0.055 - st * 0.74)
            + vsin(da * 0.062 - st * 1.05)
            + vsin(db * 0.051 + st * 0.88)
        ) * (1.0 / 6.0) + 0.5
        blob = pulse * np_mod.exp(-np_mod.minimum(da, db) * inv_diag * 2.4)
        v_idle = 0.22 + wave * 0.70 * gain + glow * 0.50 + blob * 0.55
    if not use_idle:
        wave = (
            vsin(x * 0.041 + st)
            + vsin(y * 0.036 - st * 0.81)
            + vsin((x + y) * 0.021 + st * 1.13)
            + vsin(dist * 0.048 - st * 0.47)
        ) * 0.25 + 0.5
        v_live = 0.26 + wave * 0.46 * gain + glow * 0.72
    if use_idle:
        v = v_idle
    elif use_live:
        v = v_live
    else:
        v = v_idle + (v_live - v_idle) * mix
    v = np_mod.clip(v, 0.0, 0.999)
    rgb = np_mod.ascontiguousarray(pal[(v * 255.0).astype(np_mod.int32)], dtype=np_mod.uint8)
    return pygame.image.frombuffer(rgb.tobytes(), (width, height), "RGB").convert()


def _draw_field_python(width: int, height: int, scene: dict[str, Any]) -> Any:
    import pygame

    palette, mix, st, gain, cx, cy, inv_diag, pulse, ax, ay, bx, by = _field_common(
        width, height, scene
    )
    buf = bytearray(width * height * 3)
    i = 0
    use_idle = mix <= 0.02
    use_live = mix >= 0.98
    for y in range(height):
        for x in range(width):
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx * dx + dy * dy)
            glow = pulse * math.exp(-dist * inv_diag * 3.2)
            v_idle = v_live = 0.0
            if not use_live:
                da = math.sqrt((x - ax) ** 2 + (y - ay) ** 2)
                db = math.sqrt((x - bx) ** 2 + (y - by) ** 2)
                wave = (
                    lsin(x * 0.048 + st * 1.35)
                    + lsin(y * 0.042 - st * 1.18)
                    + lsin((x + y) * 0.028 + st * 0.92)
                    + lsin(dist * 0.055 - st * 0.74)
                    + lsin(da * 0.062 - st * 1.05)
                    + lsin(db * 0.051 + st * 0.88)
                ) * (1.0 / 6.0) + 0.5
                blob = pulse * math.exp(-min(da, db) * inv_diag * 2.4)
                v_idle = 0.22 + wave * 0.70 * gain + glow * 0.50 + blob * 0.55
            if not use_idle:
                wave = (
                    lsin(x * 0.041 + st)
                    + lsin(y * 0.036 - st * 0.81)
                    + lsin((x + y) * 0.021 + st * 1.13)
                    + lsin(dist * 0.048 - st * 0.47)
                ) * 0.25 + 0.5
                v_live = 0.26 + wave * 0.46 * gain + glow * 0.72
            if use_idle:
                v = v_idle
            elif use_live:
                v = v_live
            else:
                v = v_idle + (v_live - v_idle) * mix
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


def draw_field(
    width: int,
    height: int,
    scene: dict[str, Any],
) -> Any:
    try:
        import numpy as np
    except ImportError:
        return _draw_field_python(width, height, scene)
    return _draw_field_numpy(width, height, scene, np)


def hud_font_sizes(height: int) -> tuple[int, int]:
    """pygame.Font sizes. 64/48 at 1080p, not smaller than 48/36."""
    h = max(1, int(height or 0))
    return max(48, round(h * 64 / 1080)), max(36, round(h * 48 / 1080))


def hud_halo_offsets(radius: int = 3) -> list[tuple[int, int]]:
    """Dark ring around glyphs so they stay readable on amber/white bloom."""
    r = max(1, int(radius))
    out: list[tuple[int, int]] = []
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx == 0 and dy == 0:
                continue
            if abs(dx) + abs(dy) > r + 1:
                continue
            out.append((dx, dy))
    return out


def _hud_fit(face: Any, text: str, max_w: int) -> str:
    raw = str(text or "")
    if not raw or max_w <= 0:
        return raw
    if face.size(raw)[0] <= max_w:
        return raw
    ell = "..."
    keep = raw
    while keep and face.size(keep + ell)[0] > max_w:
        keep = keep[:-1]
    return (keep + ell) if keep else ell


def draw_hud(screen: Any, font, small, scene: dict[str, Any]) -> None:
    showing = bool(scene.get("live")) or overlay_amount(scene) > 0.02
    if str(scene.get("cycle") or "") in ("boot", "halt"):
        showing = True
    if str(scene.get("palette") or "") == "down" or not scene.get("connected"):
        showing = True
    if not showing:
        return
    w, h = screen.get_size()
    profile = str(scene["profile"])
    mode = str(scene["mode"]).upper()
    phase = str(scene["phase"])
    runtime = str(scene.get("runtime") or "").strip()
    if runtime:
        phase = f"{phase}   {runtime}"
    note = str(scene.get("note") or "").strip()
    down = str(scene.get("palette") or "") == "down" or not scene.get("connected")
    if scene["connected"] and scene.get("has_gpu") and not down:
        util = int(round(scene["util"]))
        vram = int(round(scene["vram"]))
        temp = int(round(scene["temp"]))
        stats = f"GPU {util}%   VRAM {vram}%   {temp}°C"
    elif scene["connected"]:
        stats = ""
    else:
        stats = "api down"
    shadow = (0, 0, 0)
    halo = hud_halo_offsets(3)
    pad = max(32, int(round(h * 32 / 1080)))
    main_h = font.size("Ag")[1]
    small_h = small.size("Ag")[1]
    gap = max(6, int(round(h * 8 / 1080)))
    max_left = max(80, w - pad - small.size(stats)[0] - pad) if stats else w - pad * 2

    dest = str(scene.get("image_file") or "").strip()
    what = str(scene.get("image_what") or "").strip()
    n = scene.get("image_n")
    of = scene.get("image_of")
    try:
        n_i = int(round(float(n))) if n else 0
        of_i = int(round(float(of))) if of else 0
    except (TypeError, ValueError):
        n_i, of_i = 0, 0
    if dest and of_i > 1 and n_i > 0:
        dest = f"{dest}  {n_i}/{of_i}"

    def blit(text: str, pos: tuple[int, int], color, use_small: bool = False) -> None:
        face = small if use_small else font
        x, y = pos
        img = face.render(text, True, shadow)
        for dx, dy in halo:
            screen.blit(img, (x + dx, y + dy))
        screen.blit(face.render(text, True, color), pos)

    active = bool(scene.get("live")) or str(scene.get("cycle") or "") in ("boot", "halt")
    if down:
        phase_color = DOWN_TEXT
    else:
        phase_color = WARN if not scene["connected"] else (OK if active else MUTED)
    blit(profile, (pad, pad), TEXT)
    blit(mode, (w - small.size(mode)[0] - pad, pad + 4), ACCENT, use_small=True)
    y = h - pad - main_h
    extra = 0
    if dest:
        extra += 1
    if what:
        extra += 1
    if note:
        extra += 1
    if extra:
        y -= extra * (small_h + gap)
    if dest:
        blit(_hud_fit(small, dest, max_left), (pad, y), TEXT, use_small=True)
        y += small_h + gap
    if what:
        blit(_hud_fit(small, what, max_left), (pad, y), MUTED, use_small=True)
        y += small_h + gap
    if note:
        blit(_hud_fit(small, note, max_left), (pad, y), MUTED, use_small=True)
        y += small_h + gap
    blit(phase, (pad, h - pad - main_h), phase_color)
    if stats:
        blit(stats, (w - small.size(stats)[0] - pad, h - pad - small_h), MUTED, use_small=True)


def tty_nr(name: str) -> int:
    text = (name or "").strip().lower().removeprefix("/dev/")
    if text.startswith("tty"):
        return int(text[3:])
    raise ValueError(f"not a virtual console: {name}")


def evdev_is_activity(ev_type: int) -> bool:
    return ev_type in (EV_KEY, EV_REL, EV_ABS)


def should_resume_saver(
    *,
    now: float,
    last_input: float,
    idle_s: float,
    logout_idle_s: float,
    logged_in: bool,
    was_logged_in: bool | None = None,
) -> bool:
    """Show the field after idle while logged in, or after logout-idle when not."""
    del was_logged_in
    wait = idle_s if logged_in else logout_idle_s
    return (now - last_input) >= wait


def login_from_ps(text: str) -> bool:
    for raw in text.splitlines():
        comm = raw.strip().split("/")[-1]
        if comm and comm not in _GETTY_COMMS:
            return True
    return False


def console_logged_in(tty: str) -> bool:
    name = (tty or "tty1").strip().removeprefix("/dev/")
    try:
        out = subprocess.check_output(
            ["loginctl", "list-sessions", "--no-legend"],
            text=True,
            timeout=1.0,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        out = ""
    if out:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[4].removeprefix("/dev/") == name:
                return True
    try:
        ps_out = subprocess.check_output(
            ["ps", "-t", name, "-o", "comm="],
            text=True,
            timeout=1.0,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return login_from_ps(ps_out)


def activate_vt(nr: int) -> None:
    last_exc: OSError | None = None
    for path in ("/dev/tty0", "/dev/console"):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        except OSError as exc:
            last_exc = exc
            continue
        try:
            fcntl.ioctl(fd, VT_ACTIVATE, nr)
            fcntl.ioctl(fd, VT_WAITACTIVE, nr)
            return
        except OSError as exc:
            last_exc = exc
        finally:
            os.close(fd)
    if last_exc is not None:
        print(f"tabby-saver: chvt {nr} failed: {last_exc}", file=sys.stderr)


def is_dismiss_event(event: Any, pygame_mod: Any, windowed: bool) -> str | None:
    if event.type == pygame_mod.QUIT:
        return "quit"
    if windowed and event.type == pygame_mod.KEYDOWN:
        if event.key in (pygame_mod.K_ESCAPE, pygame_mod.K_q):
            return "quit"
        return None
    if windowed:
        return None
    types = {getattr(pygame_mod, name, None) for name in _DISMISS_EVENT_NAMES}
    types.discard(None)
    if event.type in types:
        return "dismiss"
    return None


class InputWatch:
    """Global keyboard/mouse timestamps while the field is not on screen."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def last(self) -> float:
        with self._lock:
            return self._last

    def bump(self) -> None:
        with self._lock:
            self._last = time.monotonic()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="saver-input", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _open_devices(self) -> list[int]:
        fds: list[int] = []
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                continue
        return fds

    def _run(self) -> None:
        fmt = "llHHi"
        size = struct.calcsize(fmt)
        fds: list[int] = []
        refresh = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= refresh:
                for fd in fds:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                fds = self._open_devices()
                refresh = now + 5.0
            if not fds:
                self._stop.wait(0.5)
                continue
            try:
                ready, _, _ = select.select(fds, [], [], 0.4)
            except (OSError, ValueError):
                refresh = 0.0
                continue
            activity = False
            for fd in ready:
                try:
                    data = os.read(fd, size * 32)
                except BlockingIOError:
                    continue
                except OSError:
                    refresh = 0.0
                    activity = False
                    break
                for off in range(0, len(data) - size + 1, size):
                    _sec, _usec, ev_type, _code, _value = struct.unpack_from(fmt, data, off)
                    if evdev_is_activity(ev_type):
                        activity = True
                        break
                if activity:
                    break
            if activity:
                self.bump()
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass


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
    parser.add_argument("--width", type=int, default=480, help="Internal field width")
    parser.add_argument("--height", type=int, default=270, help="Internal field height")
    parser.add_argument("--poll", type=float, default=0.1, help="Seconds between API polls")
    parser.add_argument(
        "--idle",
        type=float,
        default=float(os.environ.get("TABBY_SAVER_IDLE_S", "120")),
        help="Seconds without input while logged in before the field comes back (default 120)",
    )
    parser.add_argument(
        "--logout-idle",
        type=float,
        default=float(os.environ.get("TABBY_SAVER_LOGOUT_IDLE_S", "10")),
        help="Seconds without input after logout / at the login prompt (default 10)",
    )
    parser.add_argument(
        "--user-tty",
        default=os.environ.get("TABBY_SAVER_USER_TTY", "tty1"),
        help="Login/getty TTY to show when the saver dismisses",
    )
    parser.add_argument(
        "--saver-tty",
        default=os.environ.get("TABBY_SAVER_TTY", "tty8"),
        help="Virtual console the KMS field runs on",
    )
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
            "tabby-saver: pygame is missing. On Arch: sudo pacman -S --needed python-pygame python-numpy"
        ) from exc
    pygame.init()
    pygame.mouse.set_visible(False)
    allowed = [pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP]
    for name in _DISMISS_EVENT_NAMES:
        val = getattr(pygame, name, None)
        if val is not None and val not in allowed:
            allowed.append(val)
    pygame.event.set_allowed(allowed)
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


def _close_display(pygame_mod: Any) -> None:
    if pygame_mod is None:
        return
    try:
        pygame_mod.event.set_grab(False)
    except Exception:
        pass
    try:
        pygame_mod.display.quit()
    except Exception:
        pass
    try:
        pygame_mod.quit()
    except Exception:
        pass


def run_visible_field(args: argparse.Namespace, bus: StateBus, follow: SceneFollow) -> str:
    """Paint until input (kiosk) or ESC/Q (window). Returns dismiss or quit."""
    pygame, screen = _init_display(args.window)
    try:
        if not args.window:
            pygame.event.set_grab(True)
    except Exception:
        pass
    pygame.event.clear()
    font_h = -1
    font = small = None
    clock = pygame.time.Clock()
    prev = time.monotonic()
    grace_until = prev if args.window else prev + 0.6
    try:
        while True:
            now = time.monotonic()
            for event in pygame.event.get():
                action = is_dismiss_event(event, pygame, args.window)
                if action == "quit":
                    return "quit"
                if action == "dismiss" and now >= grace_until:
                    return "dismiss"
            dt = now - prev
            prev = now
            data, ok = bus.snapshot()
            scene = follow.tick(scene_from_state(data, ok), dt, now)
            field = draw_field(max(64, args.width), max(36, args.height), scene)
            screen.blit(pygame.transform.smoothscale(field, screen.get_size()), (0, 0))
            draw_neurons(pygame, screen, scene)
            draw_cycle_fx(pygame, screen, scene)
            draw_sleepers(pygame, screen, scene)
            height = screen.get_size()[1]
            if height != font_h or font is None or small is None:
                large_n, small_n = hud_font_sizes(height)
                font = pygame.font.Font(None, large_n)
                small = pygame.font.Font(None, small_n)
                font_h = height
            draw_hud(screen, font, small, scene)
            pygame.display.flip()
            clock.tick(max(8, min(30, args.fps)))
    finally:
        _close_display(pygame)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = saver_url(args.url)
    bus = StateBus()
    thread = threading.Thread(target=bus.run, args=(url, max(0.08, args.poll)), daemon=True)
    thread.start()
    follow = SceneFollow()
    watch: InputWatch | None = None
    try:
        if args.window:
            try:
                action = run_visible_field(args, bus, follow)
            except Exception as exc:
                return _drm_fail(exc)
            return 0 if action in {"quit", "dismiss"} else 0

        watch = InputWatch()
        watch.start()
        user_tty = str(args.user_tty or "tty1")
        try:
            saver_nr = tty_nr(args.saver_tty)
            user_nr = tty_nr(user_tty)
        except ValueError as exc:
            print(f"tabby-saver: {exc}", file=sys.stderr)
            return 1
        logged_in = console_logged_in(user_tty)
        show = True
        while True:
            if show:
                activate_vt(saver_nr)
                try:
                    action = run_visible_field(args, bus, follow)
                except Exception as exc:
                    print(f"tabby-saver: display failed: {exc}", file=sys.stderr)
                    time.sleep(2.0)
                    continue
                if action == "quit":
                    return 0
                watch.bump()
                logged_in = console_logged_in(user_tty)
                activate_vt(user_nr)
                show = False
                continue
            while not show:
                now = time.monotonic()
                now_login = console_logged_in(user_tty)
                if should_resume_saver(
                    now=now,
                    last_input=watch.last(),
                    idle_s=max(1.0, float(args.idle)),
                    logout_idle_s=max(0.0, float(args.logout_idle)),
                    logged_in=now_login,
                ):
                    show = True
                logged_in = now_login
                if show:
                    break
                time.sleep(0.25)
    finally:
        bus.stop.set()
        if watch is not None:
            watch.stop()
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

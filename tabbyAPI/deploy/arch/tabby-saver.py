#!/usr/bin/python
"""CPU-rendered KMSDRM kiosk: stack activity as a thermal field.

Does not import TabbyAPI or CUDA. Polls GET /v1/ui/saver/state on localhost.
Software SDL only — do not point this at a GL renderer on the LLM GPU.
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import math
import os
import select
import struct
import subprocess
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
    _HALT_S = 1.55
    _TAU_S = 2.4

    def __init__(self) -> None:
        self.intensity = 0.52
        self.speed = 0.34
        self.heat = 0.18
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
        self.overlay = 0.0
        self.cycle = "idle"
        self.cycle_t = 0.0
        self._cycle_started = 0.0

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
            self.overlay = _smoothstep(0.16 + 0.84 * self.cycle_t)
        elif self.cycle == "run":
            self.overlay = 1.0
        elif self.cycle == "halt":
            self.overlay = 1.0 - _smoothstep(self.cycle_t)
        else:
            self.overlay = 0.0
        if self.overlay < 0.002:
            self.overlay = 0.0
        tau = 0.45 if (want_live or held) else 2.2
        self.intensity = _exp_approach(self.intensity, float(target["intensity"]), dt, tau)
        self.speed = _exp_approach(self.speed, float(target["speed"]), dt, tau)
        self.heat = _exp_approach(self.heat, float(target["heat"]), dt, tau)
        self.util = _exp_approach(self.util, float(target["util"]), dt, 1.6)
        self.vram = _exp_approach(self.vram, float(target["vram"]), dt, 1.6)
        self.temp = _exp_approach(self.temp, float(target["temp"]), dt, 2.0)
        self.st += self.speed * dt
        dest = str(target.get("palette") or "idle")
        if dest not in self.weights:
            dest = "idle"
        blend_tau = 0.35 if (want_live or held) else 1.8
        for name in self.weights:
            goal = 1.0 if name == dest else 0.0
            self.weights[name] = _exp_approach(self.weights[name], goal, dt, blend_tau)
        self.palette = max(self.weights, key=lambda name: self.weights[name])
        self.mode = str(target.get("mode") or self.mode)
        self.profile = str(target.get("profile") or self.profile)
        self.connected = bool(target.get("connected"))
        if not self.connected:
            self.phase = "waiting for api"
        elif self.cycle == "boot":
            self.phase = "gearing up"
        elif self.cycle == "halt":
            self.phase = "gearing down"
        elif held:
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
            "overlay": self.overlay,
            "cycle": self.cycle,
            "cycle_t": self.cycle_t,
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
        phase, palette = "thinking", "chat"
    elif working:
        phase, palette = "in use", "chat"
    else:
        phase, palette = "idle", "idle"

    if not connected:
        phase = "waiting for api"

    if not live:
        # Idle still has to drift: a nearly-static navy field reads as frozen.
        intensity = min(0.52 + 0.18 * (vram / 100.0), 0.70)
        speed = 0.36 + 0.10 * (vram / 100.0)
        heat = max(0.10, min(0.38, 0.12 + (temp - 38.0) / 90.0))
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


def _neuron_rest(cols: int = 12, rows: int = 8) -> list[tuple[float, float]]:
    """Jittered grid that runs past the bezel so axons clip at the screen edge."""
    pts: list[tuple[float, float]] = []
    ox, oy = 0.12, 0.14
    span_x = 1.0 + 2.0 * ox
    span_y = 1.0 + 2.0 * oy
    denom_c = max(1, cols - 1)
    denom_r = max(1, rows - 1)
    for row in range(rows):
        for col in range(cols):
            i = row * cols + col
            jx = 0.035 * (_u01(i, 1) - 0.5)
            jy = 0.035 * (_u01(i, 2) - 0.5)
            x = -ox + span_x * col / denom_c + jx
            y = -oy + span_y * row / denom_r + jy
            pts.append((x, y))
    return pts


def _neuron_edges(pts: list[tuple[float, float]], cols: int = 12) -> list[tuple[int, int]]:
    n = len(pts)
    seen: set[tuple[int, int]] = set()
    edges: list[tuple[int, int]] = []
    rows = max(1, n // cols)

    def add(i: int, j: int) -> None:
        if i == j or i < 0 or j < 0 or i >= n or j >= n:
            return
        a, b = (i, j) if i < j else (j, i)
        if (a, b) in seen:
            return
        seen.add((a, b))
        edges.append((a, b))

    for row in range(rows):
        for col in range(cols):
            i = row * cols + col
            if col + 1 < cols:
                add(i, i + 1)
            if row + 1 < rows:
                add(i, i + cols)
            if col + 1 < cols and row + 1 < rows:
                add(i, i + cols + 1)
    for i, p in enumerate(pts):
        near = sorted(
            (math.hypot(p[0] - pts[j][0], p[1] - pts[j][1]), j) for j in range(n) if j != i
        )
        for _dist, j in near[:3]:
            add(i, j)
    return edges


NEURON_COLS = 12
NEURON_ROWS = 8
NEURON_REST = _neuron_rest(NEURON_COLS, NEURON_ROWS)
NEURON_EDGES = _neuron_edges(NEURON_REST, NEURON_COLS)
NEURON_SEEDS = (0, NEURON_COLS - 1, (NEURON_ROWS - 1) * NEURON_COLS, len(NEURON_REST) - 1)
NEURON_RAMPS: dict[str, list[tuple[int, int, int]]] = {
    "idle": [(90, 130, 210), (140, 175, 235), (190, 215, 250), (220, 235, 255)],
    "chat": [(40, 220, 255), (80, 150, 255), (139, 92, 246), (220, 70, 210), (255, 90, 170)],
    "image": [(255, 196, 64), (255, 140, 48), (255, 88, 72), (255, 110, 160), (255, 190, 140)],
    "switch": [(20, 200, 190), (48, 230, 130), (140, 255, 170), (200, 255, 210)],
}
NEURON_SPARK = {
    "idle": ((90, 130, 210), (210, 230, 255)),
    "chat": ((90, 160, 255), (255, 210, 240)),
    "image": ((180, 110, 40), (255, 220, 120)),
    "switch": ((40, 160, 110), (180, 255, 210)),
}


def _node_dist_norm(index: int) -> float:
    px, py = NEURON_REST[index]
    return _clamp01(math.hypot(px - 0.5, py - 0.5) / 0.72)


def _node_reveal(index: int, overlay: float, cycle: str = "", cycle_t: float = 0.0) -> float:
    dist = _node_dist_norm(index)
    if cycle == "boot":
        return _smoothstep((cycle_t + 0.10 - dist * 0.62) / 0.26)
    if cycle == "halt":
        return 1.0 - _smoothstep((cycle_t - (1.0 - dist) * 0.62) / 0.26)
    px, py = NEURON_REST[index]
    delay = 1.0
    for seed in NEURON_SEEDS:
        sx, sy = NEURON_REST[seed]
        delay = min(delay, math.hypot(px - sx, py - sy) * 0.48)
    return _smoothstep((overlay - delay) / 0.38)


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
    if overlay <= 0.02 and cycle not in ("boot", "halt"):
        return None
    st = float(scene.get("st", 0.0))
    intensity = float(scene.get("intensity") or 0.0)
    try:
        cycle_t = _clamp01(float(scene.get("cycle_t") or 0.0))
    except (TypeError, ValueError):
        cycle_t = 0.0
    if cycle in ("boot", "halt") and overlay < 0.08:
        overlay = 0.08
    nodes: list[tuple[float, float]] = []
    fires: list[float] = []
    reveal: list[float] = []
    for i, (nx, ny) in enumerate(NEURON_REST):
        vis = _node_reveal(i, overlay, cycle, cycle_t)
        reveal.append(vis)
        nodes.append(
            (
                nx + 0.012 * lsin(st * 0.33 + i * 0.37),
                ny + 0.010 * lsin(st * 0.27 + i * 0.51),
            )
        )
        rest = 0.10 + 0.10 * (0.5 + 0.5 * lsin(st * 2.3 + i * 0.91))
        pop = 0.5 + 0.5 * lsin(st * (4.1 + 0.13 * (i % 8)) + i * 1.27)
        thresh = 0.84 - 0.14 * intensity
        spike = 0.0
        if pop > thresh:
            spike = min(1.0, (pop - thresh) / max(0.04, 1.0 - thresh))
        fire = max(rest, spike) * vis
        if cycle == "boot":
            band = 1.0 - min(1.0, abs(_node_dist_norm(i) - cycle_t) / 0.16)
            fire = max(fire, band * vis)
        fires.append(fire)
    pulses: list[tuple[int, float, float]] = []
    rate = 0.45 + 0.35 * intensity
    extra = 1 + (1 if intensity > 0.88 else 0) + (1 if cycle == "boot" else 0)
    reverse = cycle == "halt"
    for ei, (a, b) in enumerate(NEURON_EDGES):
        edge_vis = min(reveal[a], reveal[b])
        if edge_vis <= 0.04:
            continue
        for p in range(extra):
            u = (st * rate * (0.50 + 0.85 * _u01(ei, p + 3)) + _u01(ei, p + 17)) % 1.0
            if reverse:
                u = 1.0 - u
            bright = (0.45 + 0.55 * intensity) * edge_vis
            pulses.append((ei, u, bright))
            width = 0.12
            if u < width:
                fires[a] = max(fires[a], (1.0 - u / width) * edge_vis)
            if u > 1.0 - width:
                fires[b] = max(fires[b], ((u - (1.0 - width)) / width) * edge_vis)
    return {
        "nodes": nodes,
        "edges": NEURON_EDGES,
        "fires": fires,
        "pulses": pulses,
        "reveal": reveal,
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


def _draw_line(pygame_mod: Any, screen: Any, color: tuple[int, int, int], a, b, width: int) -> None:
    if a == b:
        return
    pygame_mod.draw.line(screen, color, a, b, max(1, width))


def neuron_draw_sizes(fire: float, bright: float) -> tuple[int, int]:
    """Ring radius and pulse-head radius in pixels. Tests pin these thin."""
    ring = 2 if fire < 0.85 else 3
    head = 1 if bright < 0.7 else 2
    return ring, head


def draw_neurons(pygame_mod: Any, screen: Any, scene: dict[str, Any]) -> None:
    state = neuron_overlay_state(scene)
    if state is None:
        return
    w, h = screen.get_size()
    overlay = float(state["overlay"])
    name = str(scene.get("palette") or "chat")
    axon, spark = NEURON_SPARK.get(name) or NEURON_SPARK["chat"]
    nodes = [(int(round(x * w)), int(round(y * h))) for x, y in state["nodes"]]
    edges: list[tuple[int, int]] = state["edges"]
    reveal: list[float] = state["reveal"]
    for a, b in edges:
        vis = min(reveal[a], reveal[b]) * overlay
        if vis <= 0.03 or nodes[a] == nodes[b]:
            continue
        _draw_line(pygame_mod, screen, _mix(BG, axon, 0.42 * vis), nodes[a], nodes[b], 1)
    for ei, u, bright in state["pulses"]:
        a, b = edges[ei]
        x0, y0 = nodes[a]
        x1, y1 = nodes[b]
        vis = bright * overlay
        px = int(round(x0 + (x1 - x0) * u))
        py = int(round(y0 + (y1 - y0) * u))
        color = _mix(axon, spark, vis)
        _, head = neuron_draw_sizes(0.0, vis)
        pygame_mod.draw.circle(screen, color, (px, py), head)
        if head > 1:
            pygame_mod.draw.circle(screen, (255, 255, 255), (px, py), 1)
    fires: list[float] = state["fires"]
    for i, (x, y) in enumerate(nodes):
        vis = reveal[i] * overlay
        if vis <= 0.03:
            continue
        fire = fires[i]
        body = _mix(axon, spark, fire)
        ring, _head = neuron_draw_sizes(fire, 0.0)
        pygame_mod.draw.circle(screen, _mix(BG, body, (0.55 + 0.45 * fire) * vis), (x, y), ring)
        pygame_mod.draw.circle(screen, _mix(BG, body, vis), (x, y), max(1, ring - 1))
        if fire > 0.35 and vis > 0.35:
            pygame_mod.draw.circle(screen, (255, 255, 255), (x, y), 1)


def draw_cycle_fx(pygame_mod: Any, screen: Any, scene: dict[str, Any]) -> None:
    """Center bloom + ring: gearing up expands, gearing down contracts. Field stays on."""
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


def draw_hud(screen: Any, font, small, scene: dict[str, Any]) -> None:
    showing = bool(scene.get("live")) or overlay_amount(scene) > 0.02
    if str(scene.get("cycle") or "") in ("boot", "halt"):
        showing = True
    if not showing:
        return
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

    active = bool(scene.get("live")) or str(scene.get("cycle") or "") in ("boot", "halt")
    phase_color = WARN if not scene["connected"] else (OK if active else MUTED)
    blit(profile, (28, 22), TEXT)
    blit(mode, (w - small.size(mode)[0] - 28, 26), ACCENT, use_small=True)
    blit(phase, (28, h - 52), phase_color)
    blit(stats, (w - small.size(stats)[0] - 28, h - 50), MUTED, use_small=True)


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
    parser.add_argument("--width", type=int, default=256, help="Internal field width")
    parser.add_argument("--height", type=int, default=144, help="Internal field height")
    parser.add_argument("--poll", type=float, default=0.25, help="Seconds between API polls")
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
            "tabby-saver: pygame is missing. On Arch: sudo pacman -S --needed python-pygame"
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
    font = pygame.font.Font(None, 36)
    small = pygame.font.Font(None, 28)
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
            draw_hud(screen, font, small, scene)
            pygame.display.flip()
            clock.tick(max(8, min(30, args.fps)))
    finally:
        _close_display(pygame)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = saver_url(args.url)
    bus = StateBus()
    thread = threading.Thread(target=bus.run, args=(url, max(0.15, args.poll)), daemon=True)
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

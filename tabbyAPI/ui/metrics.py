"""Host metrics history for the Status page charts.

Samples CPU, load, RAM, and NVIDIA GPU stats on a timer while TabbyAPI
runs. Persists to logs/ui_metrics.jsonl so hour/day views survive restarts.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "logs" / "ui_metrics.jsonl"
SAMPLE_INTERVAL_S = 30
MAX_AGE_S = 30 * 24 * 3600  # keep 30 days
MAX_POINTS_DEFAULT = 720
MAX_HOURS = 30 * 24
MAX_DAYS = 30

_lock = threading.RLock()
_samples: list[dict[str, Any]] = []
_task: Optional[asyncio.Task] = None
_started = False
_cpu_primed = False


def history_path() -> Path:
    return HISTORY_PATH


def _prime_cpu() -> None:
    global _cpu_primed
    try:
        import psutil

        psutil.cpu_percent(interval=None)
        _cpu_primed = True
    except Exception:
        _cpu_primed = False


def take_sample(now: Optional[float] = None) -> dict[str, Any]:
    """Collect one metrics point. Safe if nvidia-smi / psutil are missing."""
    global _cpu_primed
    stamp = float(now if now is not None else time.time())
    cpu = None
    ram = None
    load1 = None
    try:
        import psutil

        if not _cpu_primed:
            psutil.cpu_percent(interval=None)
            _cpu_primed = True
            cpu = float(psutil.cpu_percent(interval=0.05))
        else:
            cpu = float(psutil.cpu_percent(interval=None))
        ram = float(psutil.virtual_memory().percent)
    except Exception:
        pass
    try:
        load1 = float(os.getloadavg()[0])
    except (OSError, AttributeError):
        pass

    from ui.manager import nvidia_stats

    gpu = nvidia_stats()
    util = gpu.get("utilization_pct")
    used = gpu.get("memory_used_mib")
    total = gpu.get("memory_total_mib")
    temp = gpu.get("temperature_c")
    vram_pct = None
    if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total > 0:
        vram_pct = round(100.0 * float(used) / float(total), 2)

    return {
        "t": stamp,
        "cpu": None if cpu is None else round(cpu, 2),
        "load1": None if load1 is None else round(load1, 3),
        "ram": None if ram is None else round(ram, 2),
        "gpu": None if util is None else float(util),
        "vram": vram_pct,
        "vram_mib": used,
        "temp": None if temp is None else float(temp),
    }


def _prune_locked(now: Optional[float] = None) -> None:
    cutoff = float(now if now is not None else time.time()) - MAX_AGE_S
    while _samples and float(_samples[0].get("t") or 0) < cutoff:
        _samples.pop(0)


def _load_history() -> None:
    path = history_path()
    if not path.is_file():
        return
    loaded: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or "t" not in row:
            continue
        loaded.append(row)
    with _lock:
        _samples.clear()
        _samples.extend(sorted(loaded, key=lambda r: float(r.get("t") or 0)))
        _prune_locked()


def _rewrite_history_locked() -> None:
    path = history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for row in _samples:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        tmp.replace(path)
    except OSError as exc:
        logger.warning(f"Could not write metrics history: {exc}")


def _append_history_locked(row: dict[str, Any]) -> None:
    path = history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.warning(f"Could not append metrics sample: {exc}")


def record_sample(row: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    sample = row or take_sample()
    with _lock:
        _samples.append(sample)
        _prune_locked(sample.get("t"))
        # Rewrite occasionally so pruned points leave the file.
        if len(_samples) % 120 == 0:
            _rewrite_history_locked()
        else:
            _append_history_locked(sample)
    return sample


def resolve_window_seconds(
    *,
    hours: Optional[float] = None,
    days: Optional[float] = None,
    default_hours: float = 24.0,
) -> float:
    """Prefer custom days, then hours, else default. Clamped to 30 days."""
    if days is not None:
        try:
            value = float(days)
        except (TypeError, ValueError):
            value = float(default_hours) / 24.0
        value = max(1.0 / 24.0, min(float(MAX_DAYS), value))
        return value * 3600.0 * 24.0
    if hours is not None:
        try:
            value = float(hours)
        except (TypeError, ValueError):
            value = float(default_hours)
        value = max(1.0 / 60.0, min(float(MAX_HOURS), value))
        return value * 3600.0
    return float(default_hours) * 3600.0


def downsample(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if max_points < 2 or len(points) <= max_points:
        return list(points)
    out: list[dict[str, Any]] = []
    n = len(points)
    for i in range(max_points):
        start = int(i * n / max_points)
        end = int((i + 1) * n / max_points)
        chunk = points[start:end] or [points[min(start, n - 1)]]
        if i == max_points - 1:
            chunk = points[start:] or chunk
        acc: dict[str, list[float]] = {}
        t_vals: list[float] = []
        for row in chunk:
            t_vals.append(float(row.get("t") or 0))
            for key, val in row.items():
                if key == "t" or val is None:
                    continue
                if isinstance(val, (int, float)):
                    acc.setdefault(key, []).append(float(val))
        merged: dict[str, Any] = {"t": t_vals[len(t_vals) // 2] if t_vals else 0}
        for key, vals in acc.items():
            merged[key] = round(sum(vals) / len(vals), 3)
        out.append(merged)
    return out


def metrics_history(
    *,
    hours: Optional[float] = None,
    days: Optional[float] = None,
    max_points: int = MAX_POINTS_DEFAULT,
) -> dict[str, Any]:
    window_s = resolve_window_seconds(hours=hours, days=days)
    now = time.time()
    cutoff = now - window_s
    with _lock:
        points = [row for row in _samples if float(row.get("t") or 0) >= cutoff]
    capped = max(2, min(int(max_points or MAX_POINTS_DEFAULT), 5000))
    series = downsample(points, capped)
    return {
        "ok": True,
        "now": now,
        "window_s": window_s,
        "hours": round(window_s / 3600.0, 4),
        "days": round(window_s / 86400.0, 4),
        "interval_s": SAMPLE_INTERVAL_S,
        "count": len(series),
        "raw_count": len(points),
        "series": series,
        "keys": {
            "cpu": "CPU %",
            "load1": "Load (1m)",
            "ram": "RAM %",
            "gpu": "GPU util %",
            "vram": "VRAM %",
            "temp": "GPU °C",
        },
    }


async def _sampler_loop() -> None:
    _prime_cpu()
    await asyncio.sleep(1.0)
    while True:
        try:
            await asyncio.to_thread(record_sample)
        except Exception as exc:
            logger.warning(f"Metrics sample failed: {exc}")
        await asyncio.sleep(SAMPLE_INTERVAL_S)


def ensure_metrics_sampler() -> None:
    """Load history once and start the background sampler if needed."""
    global _task, _started
    with _lock:
        if not _started:
            _load_history()
            _started = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _task is not None and not _task.done():
        return
    _task = loop.create_task(_sampler_loop(), name="ui-metrics-sampler")


def reset_for_tests() -> None:
    """Clear in-memory state (unit tests only)."""
    global _task, _started, _cpu_primed
    with _lock:
        _samples.clear()
        _started = False
        _cpu_primed = False
        _task = None

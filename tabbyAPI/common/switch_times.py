"""Warm-switch wait copy from model_profiles/switch_times.json."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
TIMES_PATH = ROOT / "model_profiles" / "switch_times.json"

# Used when the file is missing. Bench overwrites the JSON with measured values.
DEFAULT_READY_S = {
    "qwen": 66,
    "qwen35": 170,
    "qwen36": 87,
    "gemma": 65,
    "gemma26": 99,
    "glm": 13,
    "comfy": 37,
    "flux": 37,
    "llm": 64,
}


def detect_gpu() -> dict[str, Any]:
    """nvidia-smi name + total MiB. Empty strings if the tool is missing."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
        )
        line = out.strip().splitlines()[0]
        name, _, mem = line.partition(",")
        name = name.strip()
        try:
            vram_mib = int(float(mem.strip()))
        except ValueError:
            vram_mib = 0
        gb = max(1, int(round(vram_mib / 1024.0))) if vram_mib else 0
        short = name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
        label = f"{short} {gb} GB" if gb else short or "unknown GPU"
        return {"name": name or "unknown", "vram_mib": vram_mib, "label": label}
    except (OSError, subprocess.CalledProcessError, IndexError):
        return {"name": "unknown", "vram_mib": 0, "label": "unknown GPU"}


def load_switch_times(path: Optional[Path] = None) -> dict[str, Any]:
    target = path or TIMES_PATH
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def gpu_label(times: Optional[dict[str, Any]] = None) -> str:
    """Label from switch_times.json, else nvidia-smi (e.g. 'RTX 4070 Ti 12 GB')."""
    data = times if times is not None else load_switch_times()
    label = data.get("gpu") if isinstance(data, dict) else None
    if isinstance(label, str) and label.strip():
        return label.strip()
    return str(detect_gpu().get("label") or "this GPU")


def ready_seconds(name: str, times: Optional[dict[str, Any]] = None) -> int:
    """Typical seconds until the GPU is ready for this switch alias."""
    key = (name or "").strip().lower()
    if key in ("flux", "image", "comfyui"):
        key = "comfy"
    data = times if times is not None else load_switch_times()
    entry = data.get(key)
    if isinstance(entry, dict) and entry.get("ready_s") is not None:
        try:
            return max(1, int(round(float(entry["ready_s"]))))
        except (TypeError, ValueError):
            pass
    if isinstance(entry, (int, float)):
        return max(1, int(round(float(entry))))
    return DEFAULT_READY_S.get(key, DEFAULT_READY_S["qwen"])


def format_duration(seconds: float) -> str:
    """'15 seconds' or '2 minutes' — no leading 'about'."""
    secs = max(1, float(seconds))
    if secs < 90:
        rounded = int(5 * round(secs / 5.0)) if secs >= 5 else int(round(secs))
        rounded = max(1, rounded)
        unit = "second" if rounded == 1 else "seconds"
        return f"{rounded} {unit}"
    minutes = max(1, int(round(secs / 60.0)))
    unit = "minute" if minutes == 1 else "minutes"
    return f"{minutes} {unit}"


def wait_hint(name: str, times: Optional[dict[str, Any]] = None) -> str:
    """'Wait about 15 seconds' / 'Wait about 2 minutes'."""
    return f"Wait about {format_duration(ready_seconds(name, times))}"


def profile_error(name: str, times: Optional[dict[str, Any]] = None) -> Optional[str]:
    key = (name or "").strip().lower()
    data = times if times is not None else load_switch_times()
    entry = data.get(key)
    if isinstance(entry, dict):
        err = entry.get("error")
        if err:
            return str(err)
    return None


def extra_seconds(name: str, field: str, times: Optional[dict[str, Any]] = None) -> Optional[int]:
    key = (name or "").strip().lower()
    if key in ("flux", "image", "comfyui"):
        key = "comfy"
    data = times if times is not None else load_switch_times()
    entry = data.get(key)
    if not isinstance(entry, dict) or entry.get(field) is None:
        return None
    try:
        return max(1, int(round(float(entry[field]))))
    except (TypeError, ValueError):
        return None

"""Guards for VRAM-fail recovery: one bounce, then fall back to qwen."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from common.switch_times import ready_seconds

ROOT = Path(__file__).resolve().parent.parent
RECOVER_PATH = ROOT / "model_profiles" / "vram_recover.json"
FALLBACK_PROFILE = "qwen"
BOUNCE_COOLDOWN_S = 10 * 60
VRAM_MARKERS = (
    "Insufficient VRAM",
    "out of memory",
    "OutOfMemory",
    "CUDA out of memory",
)


def is_vram_error(exc: object) -> bool:
    text = str(exc)
    return any(marker in text for marker in VRAM_MARKERS)


def health_timeout_s(profile: str) -> float:
    """Wait long enough for a cold load after a bounce, with a hard cap."""
    return min(360.0, max(180.0, float(ready_seconds(profile)) + 90.0))


def read_state() -> dict[str, Any]:
    if not RECOVER_PATH.is_file():
        return {}
    try:
        data = json.loads(RECOVER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(state: dict[str, Any]) -> None:
    try:
        RECOVER_PATH.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def bounce_is_cooling(now: Optional[float] = None) -> bool:
    bounced = read_state().get("bounced_at")
    if not isinstance(bounced, (int, float)):
        return False
    return float(now if now is not None else time.time()) - float(bounced) < BOUNCE_COOLDOWN_S


def mark_bounce(profile: str) -> None:
    write_state(
        {
            "bounced_at": time.time(),
            "profile": profile,
            "action": "bounce",
        }
    )


def mark_fallback(failed: str, fallback: str) -> None:
    write_state(
        {
            "bounced_at": read_state().get("bounced_at"),
            "profile": failed,
            "action": "fallback",
            "fallback": fallback,
            "fallback_at": time.time(),
        }
    )

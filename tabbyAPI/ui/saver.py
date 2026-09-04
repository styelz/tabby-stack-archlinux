"""Localhost-only snapshot for the TTY kiosk screensaver.

The payload is GPU/occupancy weather only: no prompts, usernames, or chat ids.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import HTTPException, Request

SAFE_KINDS = frozenset({"chat", "code", "image", "gpu"})
_LEAK_KEYS = frozenset(
    {
        "occupant",
        "prompt",
        "chat_id",
        "user",
        "hint",
        "job",
        "stack_queue",
        "profiles",
        "profile_labels",
        "api_base",
    }
)


def _ip_is_loopback(host: str) -> bool:
    text = (host or "").strip().strip("[]")
    if not text:
        return False
    if text.lower() in {"localhost", "127.0.0.1", "::1"}:
        return True
    if text.lower().startswith("::ffff:"):
        text = text[7:]
    try:
        return bool(ipaddress.ip_address(text).is_loopback)
    except ValueError:
        return False


def peer_is_loopback(request: Request) -> bool:
    """True only when the TCP peer (and any forwarded client) is loopback.

    A local reverse proxy that forwards a public client is rejected: the
    screensaver feed is for the GPU host's own kiosk, not the LAN.
    """
    peer = ""
    client = getattr(request, "client", None)
    if client is not None:
        peer = str(getattr(client, "host", "") or "")
    if not _ip_is_loopback(peer):
        return False
    headers = getattr(request, "headers", None) or {}
    forwarded = ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        forwarded = (getter("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded and not _ip_is_loopback(forwarded):
        return False
    return True


def require_loopback(request: Request) -> None:
    if not peer_is_loopback(request):
        raise HTTPException(403, "Saver state is localhost only.")


def _kind(raw: Any) -> str | None:
    text = str(raw or "").strip()
    return text if text in SAFE_KINDS else None


def _vram_pct(gpu: dict[str, Any]) -> int | None:
    used = gpu.get("memory_used_mib")
    total = gpu.get("memory_total_mib")
    try:
        used_n = float(used)
        total_n = float(total)
    except (TypeError, ValueError):
        return None
    if total_n <= 0:
        return None
    return int(round(100.0 * used_n / total_n))


def sanitize_status(raw: dict[str, Any]) -> dict[str, Any]:
    """Whitelist the fields a wall monitor may show."""
    gpu = raw.get("gpu") if isinstance(raw.get("gpu"), dict) else {}
    host = raw.get("host") if isinstance(raw.get("host"), dict) else {}
    queue = raw.get("stack_queue") if isinstance(raw.get("stack_queue"), dict) else {}
    profile = str(raw.get("profile") or "").strip() or None
    gpu_mode = str(raw.get("gpu_mode") or "").strip() or None
    payload = {
        "ok": True,
        "gpu_mode": gpu_mode,
        "profile": profile,
        "busy": bool(raw.get("busy") or queue.get("busy") or queue.get("live")),
        "switching": bool(raw.get("switching")),
        "restarting": bool(raw.get("restarting")),
        "kind": _kind(queue.get("kind")),
        "gpu": {
            "utilization_pct": gpu.get("utilization_pct"),
            "vram_pct": _vram_pct(gpu),
            "temperature_c": gpu.get("temperature_c"),
        },
        "host": {
            "cpu_pct": host.get("cpu_pct"),
        },
    }
    leaked = _LEAK_KEYS.intersection(payload)
    if leaked:
        raise RuntimeError(f"saver payload leaked {sorted(leaked)}")
    return payload


async def saver_state() -> dict[str, Any]:
    """Occupancy weather only — never wait on nvidia-smi or HealthManager.

    The kiosk needs to see a prompt the moment StackGate is taken. Full
    stack_status blocks the event loop on nvidia-smi (up to 5s), which is why
    the field used to sit idle for several seconds after a chat started.
    """
    from common.gpu_mode import read_mode
    from common.phrase_switch import (
        last_llm_profile_name,
        profile_alias_for_model,
        switch_lock_held,
        switch_lock_name,
    )
    from images.jobs import loaded_tabby_name
    from select_model import last_profile
    from ui.occupancy import snapshot as stack_queue_snapshot

    mode = read_mode()
    tabby = loaded_tabby_name()
    gpu_mode = "llm" if tabby else (mode.get("mode") or "llm")
    lock_name = switch_lock_name()
    lock_held = switch_lock_held()
    restarting = lock_held and lock_name == "restart"
    switching = lock_held and not restarting
    profile = profile_alias_for_model(tabby) or last_llm_profile_name() or last_profile()
    queue = stack_queue_snapshot("")
    return sanitize_status(
        {
            "gpu_mode": gpu_mode,
            "profile": profile,
            "busy": bool(lock_held) or bool(queue.get("busy")),
            "switching": switching,
            "restarting": restarting,
            "stack_queue": queue,
        }
    )

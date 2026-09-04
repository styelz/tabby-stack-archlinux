"""In-process decode weather for the TTY kiosk. Numbers only — never text."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_request_id: str | None = None
_tokens: int = 0
_stage: str = "idle"


def note_prefill(request_id: str) -> None:
    rid = str(request_id or "").strip()
    if not rid:
        return
    with _lock:
        global _request_id, _tokens, _stage
        _request_id = rid
        _tokens = 0
        _stage = "prefill"


def note_decode(request_id: str, tokens: int) -> None:
    rid = str(request_id or "").strip()
    if not rid:
        return
    try:
        count = int(tokens)
    except (TypeError, ValueError):
        count = 0
    if count < 0:
        count = 0
    with _lock:
        global _request_id, _tokens, _stage
        if _request_id and _request_id != rid:
            return
        _request_id = rid
        _tokens = count
        _stage = "decode"


def clear(request_id: str | None = None) -> None:
    rid = str(request_id or "").strip()
    with _lock:
        global _request_id, _tokens, _stage
        if rid and _request_id and _request_id != rid:
            return
        _request_id = None
        _tokens = 0
        _stage = "idle"


def snapshot() -> dict[str, Any]:
    with _lock:
        return {"tokens": int(_tokens), "stage": str(_stage)}


def reset_for_tests() -> None:
    clear()

"""In-process decode weather for the TTY kiosk. Numbers only — never text."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_holders: set[str] = set()
_request_id: str | None = None
_tokens: int = 0
_stage: str = "idle"


def is_generate_post(method: str, path: str) -> bool:
    """True for Chat Completions / completions / console chat POSTs."""
    if str(method or "").upper() != "POST":
        return False
    text = (path or "").split("?", 1)[0].rstrip("/") or "/"
    if text.endswith("/v1/ui/chat"):
        return True
    if text.endswith("/chat/completions"):
        return True
    if text.endswith("/v1/completions") or text == "/completions":
        return True
    return False


def _idle_locked() -> None:
    global _request_id, _tokens, _stage
    _request_id = None
    _tokens = 0
    _stage = "idle"


def hold(key: str, *, stage: str = "prefill") -> None:
    """Mark an in-flight generate POST or GPU job. Does not wait on the model."""
    token = str(key or "").strip()
    if not token:
        return
    want = str(stage or "prefill").strip().lower()
    if want not in {"prefill", "decode"}:
        want = "prefill"
    with _lock:
        global _stage
        _holders.add(token)
        if want == "decode":
            _stage = "decode"
        elif _stage != "decode":
            _stage = "prefill"


def release(key: str) -> None:
    token = str(key or "").strip()
    with _lock:
        if token:
            _holders.discard(token)
        if _holders:
            return
        _idle_locked()


def note_prefill(request_id: str) -> None:
    rid = str(request_id or "").strip()
    if not rid:
        return
    with _lock:
        global _request_id, _tokens, _stage
        _holders.add(rid)
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
        _holders.add(rid)
        _request_id = rid
        _tokens = count
        _stage = "decode"


def clear(request_id: str | None = None) -> None:
    rid = str(request_id or "").strip()
    with _lock:
        global _request_id, _tokens, _stage
        if rid:
            _holders.discard(rid)
            if _request_id and _request_id != rid:
                if _holders:
                    return
                return
        else:
            _holders.clear()
        if _holders:
            return
        _idle_locked()


def snapshot() -> dict[str, Any]:
    with _lock:
        stage = str(_stage)
        if stage == "idle" and _holders:
            stage = "prefill"
        return {"tokens": int(_tokens), "stage": stage}


def reset_for_tests() -> None:
    with _lock:
        _holders.clear()
        _idle_locked()

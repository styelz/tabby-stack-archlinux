"""Serialize UI console chat when the GPU or model is already in use."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

QUEUE_MARK = "tabby-stack-queue:"
QUEUE_HINT = "The stack is being used. You are in a queue."

_cond = asyncio.Condition()
_occupant: Optional["Occupant"] = None
_waiters: list["Waiter"] = []


@dataclass
class Occupant:
    id: str
    username: str
    started_at: float
    kind: str = "chat"


@dataclass
class Waiter:
    id: str
    username: str
    queued_at: float
    kind: str = "chat"


def _externally_busy() -> bool:
    try:
        from images.jobs import active_mcp_image_job

        job = active_mcp_image_job()
        if job and job.status in ("queued", "running"):
            return True
    except Exception:
        pass
    try:
        from common import model as tabby_model

        container = tabby_model.container
        jobs = getattr(container, "active_job_ids", None) if container is not None else None
        if jobs:
            return True
    except Exception:
        pass
    return False


def snapshot(username: str = "") -> dict[str, Any]:
    occupant = _occupant
    waiters = list(_waiters)
    who = (username or "").strip()
    position = None
    queued_at = None
    for index, waiter in enumerate(waiters, start=1):
        if who and waiter.username == who:
            position = index
            queued_at = waiter.queued_at
            break
    now = time.time()
    return {
        "busy": occupant is not None or bool(waiters) or _externally_busy(),
        "queued": position is not None,
        "position": position,
        "waiters": len(waiters),
        "kind": occupant.kind if occupant else None,
        "elapsed_s": int(now - occupant.started_at) if occupant else 0,
        "queued_elapsed_s": int(now - queued_at) if queued_at else 0,
        "hint": queue_text({"position": position or 0}),
    }


def queue_text(info: Optional[dict[str, Any]] = None) -> str:
    position = int((info or {}).get("position") or 0)
    if position > 1:
        return f"{QUEUE_HINT} You are number {position}."
    return QUEUE_HINT


def queue_comment(info: Optional[dict[str, Any]] = None) -> str:
    return f"{QUEUE_MARK} {queue_text(info)}"


async def try_acquire(username: str, *, kind: str = "chat") -> Optional[str]:
    """Take the slot if nothing else is waiting or running."""
    global _occupant
    async with _cond:
        if _occupant is not None or _waiters or _externally_busy():
            return None
        occupant = Occupant(
            id=uuid4().hex,
            username=username or "",
            started_at=time.time(),
            kind=kind,
        )
        _occupant = occupant
        return occupant.id


async def enqueue(username: str, *, kind: str = "chat") -> Waiter:
    async with _cond:
        waiter = Waiter(
            id=uuid4().hex,
            username=username or "",
            queued_at=time.time(),
            kind=kind,
        )
        _waiters.append(waiter)
        return waiter


async def promote(waiter: Waiter) -> Optional[str]:
    global _occupant
    async with _cond:
        if _occupant is not None:
            return None
        if not _waiters or _waiters[0].id != waiter.id:
            return None
        if _externally_busy():
            return None
        _waiters.pop(0)
        occupant = Occupant(
            id=waiter.id,
            username=waiter.username,
            started_at=time.time(),
            kind=waiter.kind,
        )
        _occupant = occupant
        return occupant.id


async def drop_waiter(waiter: Waiter) -> None:
    async with _cond:
        _waiters[:] = [item for item in _waiters if item.id != waiter.id]
        _cond.notify_all()


async def release(occupant_id: Optional[str]) -> None:
    global _occupant
    if not occupant_id:
        return
    async with _cond:
        if _occupant and _occupant.id == occupant_id:
            _occupant = None
            _cond.notify_all()


async def wait_tick(timeout: float = 1.0) -> None:
    async with _cond:
        try:
            await asyncio.wait_for(_cond.wait(), timeout)
        except asyncio.TimeoutError:
            return


class StackGate:
    """One UI chat request: take the GPU slot or wait in line."""

    def __init__(self, username: str, *, kind: str = "chat"):
        self.username = username or ""
        self.kind = kind
        self.occupant_id: Optional[str] = None
        self.waiter: Optional[Waiter] = None

    async def step(self, disconnect_handler) -> Optional[dict[str, Any]]:
        """None once this request owns the stack; otherwise a queue snapshot."""
        if self.occupant_id:
            return None
        if self.waiter is None:
            self.occupant_id = await try_acquire(self.username, kind=self.kind)
            if self.occupant_id:
                return None
            self.waiter = await enqueue(self.username, kind=self.kind)
        await disconnect_handler.poll()
        occupant_id = await promote(self.waiter)
        if occupant_id:
            self.occupant_id = occupant_id
            self.waiter = None
            return None
        return snapshot(self.username)

    async def release(self) -> None:
        waiter = self.waiter
        occupant_id = self.occupant_id
        self.waiter = None
        self.occupant_id = None
        if waiter is not None:
            await drop_waiter(waiter)
        await release(occupant_id)

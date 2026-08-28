"""Console chat generation that survives a page reload.

The GPU job is a background task. SSE clients subscribe to it; hanging up
only unsubscribes. Stop still sets abort_event.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi.responses import StreamingResponse
from sse_starlette import ServerSentEvent

_FLIGHTS: dict[str, "ConsoleFlight"] = {}
_DROP_AFTER_S = 30


def reset_for_tests() -> None:
    _FLIGHTS.clear()


def get_flight(username: str) -> Optional["ConsoleFlight"]:
    return _FLIGHTS.get(str(username or "").strip())


def abort_flight(username: str) -> bool:
    flight = get_flight(username)
    if flight is None:
        return False
    flight.abort_event.set()
    return True


def snapshot_for(username: str) -> Optional[dict[str, Any]]:
    flight = get_flight(username)
    if flight is None:
        return None
    return {
        "chat_id": flight.chat_id,
        "prompt": flight.prompt,
        "kind": flight.kind,
        "live": not flight.done,
    }


def _sse_ping() -> bytes:
    """Comment that matches sse-starlette / tabbyIsSsePing keep-alives."""
    return f": ping - {datetime.now(timezone.utc)}\n\n".encode("utf-8")


def as_bytes(item: Any) -> bytes:
    if item is None:
        return b""
    if isinstance(item, (bytes, bytearray, memoryview)):
        raw = bytes(item)
        return raw if raw else b""
    if isinstance(item, ServerSentEvent):
        encoded = item.encode()
        return encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")
    text = str(item)
    if text.startswith("data:") or text.startswith(":"):
        if not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return text.encode("utf-8")
    encoded = ServerSentEvent(data=text, sep="\n").encode()
    return encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")


class ConsoleFlight:
    def __init__(self, username: str, chat_id: str, kind: str, prompt: str, agent: str = ""):
        self.id = uuid4().hex
        self.username = str(username or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.kind = str(kind or "chat")
        self.agent = str(agent or "").strip()
        self.prompt = str(prompt or "").replace("\n", " ").strip()[:200]
        self.started_at = time.time()
        self.abort_event = asyncio.Event()
        self.chunks: list[bytes] = []
        self.queues: list[asyncio.Queue] = []
        self.lock = asyncio.Lock()
        self.done = False
        self._closing = False
        self.assembled = ""
        self.reasoning = ""
        self.status_label = ""
        self.steps: list[dict[str, Any]] = []
        self._parse_buf = ""
        self.task: Optional[asyncio.Task] = None

    def ingest(self, raw: bytes) -> None:
        self._parse_buf += raw.decode("utf-8", errors="replace")
        while "\n\n" in self._parse_buf:
            block, self._parse_buf = self._parse_buf.split("\n\n", 1)
            self._ingest_block(block)

    def _ingest_block(self, chunk: str) -> None:
        comments = [
            line[1:].strip()
            for line in chunk.split("\n")
            if line.startswith(":")
        ]
        for comment in comments:
            if "tabby-image-status:" in comment:
                self.status_label = comment.split("tabby-image-status:", 1)[-1].strip()
            elif "tabby-stack-queue:" in comment:
                self.status_label = "Queued"
            elif "tabby-agent-step:" in comment:
                raw = comment.split("tabby-agent-step:", 1)[-1].strip()
                try:
                    step = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(step, dict):
                    continue
                if step.get("type") == "demote":
                    draft = self.assembled.strip()
                    if draft:
                        self.steps.append({"type": "said", "content": draft})
                    self.assembled = ""
                else:
                    self.steps.append(step)
        data_lines = [
            line[5:].strip()
            for line in chunk.split("\n")
            if line.startswith("data:")
        ]
        if not data_lines:
            return
        payload = "\n".join(data_lines)
        if payload == "[DONE]":
            return
        try:
            parsed = json.loads(payload)
        except ValueError:
            if payload:
                self.assembled += payload
            return
        if not isinstance(parsed, dict):
            return
        choice = (parsed.get("choices") or [{}])[0] or {}
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        content = delta.get("content") or message.get("content") or parsed.get("line") or ""
        reasoning = delta.get("reasoning_content") or message.get("reasoning_content") or ""
        if content:
            self.assembled += str(content)
        if reasoning:
            self.reasoning += str(reasoning)

    async def publish(self, item: Any) -> None:
        raw = as_bytes(item)
        if not raw:
            return
        self.ingest(raw)
        async with self.lock:
            self.chunks.append(raw)
            waiters = list(self.queues)
        for queue in waiters:
            await queue.put(raw)

    async def subscribe(self, ping_s: Optional[float] = None):
        queue: asyncio.Queue = asyncio.Queue()
        async with self.lock:
            history = list(self.chunks)
            finished = self.done or self._closing
            if not finished:
                self.queues.append(queue)
        for item in history:
            yield item
        if finished:
            return
        idle_ping = bool(ping_s and ping_s < 1_000_000)
        try:
            while True:
                if idle_ping:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=float(ping_s))
                    except asyncio.TimeoutError:
                        yield _sse_ping()
                        continue
                else:
                    item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            async with self.lock:
                if queue in self.queues:
                    self.queues.remove(queue)

    async def finish(self) -> None:
        async with self.lock:
            if self.done or self._closing:
                return
            self._closing = True
            waiters = list(self.queues)
            self.queues.clear()
        if self.chat_id and (
            self.assembled.strip() or self.reasoning.strip() or self.steps
        ):
            from ui.chats import append_flight_assistant

            elapsed = max(1, int(time.time() - self.started_at))
            append_flight_assistant(
                self.username,
                self.chat_id,
                content=self.assembled,
                reasoning=self.reasoning,
                elapsed_s=elapsed,
                status_label=self.status_label,
                steps=self.steps,
                agent=self.agent,
            )
        async with self.lock:
            self.done = True
        for queue in waiters:
            await queue.put(None)


def register_flight(flight: ConsoleFlight) -> ConsoleFlight:
    previous = _FLIGHTS.get(flight.username)
    _FLIGHTS[flight.username] = flight
    if previous is not None and previous is not flight and not previous.done:
        previous.abort_event.set()
    return flight


async def _drop_later(flight: ConsoleFlight) -> None:
    await asyncio.sleep(_DROP_AFTER_S)
    if _FLIGHTS.get(flight.username) is flight:
        _FLIGHTS.pop(flight.username, None)


async def close_flight(flight: ConsoleFlight) -> None:
    await flight.finish()
    asyncio.create_task(_drop_later(flight))


def stream_response(flight: Optional[ConsoleFlight]) -> StreamingResponse:
    async def _body():
        if flight is None:
            yield b"data: [DONE]\n\n"
            return
        from common.networking import get_sse_ping_interval

        # This response is not EventSourceResponse, so it does not inherit
        # sse-starlette pings. A long Code/Plan prefill would otherwise sit
        # silent until a proxy or browser drops it as a network error.
        async for chunk in flight.subscribe(ping_s=get_sse_ping_interval()):
            if chunk:
                yield chunk

    return StreamingResponse(
        _body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

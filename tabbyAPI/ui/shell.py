"""Jailed project shell for UI Code mode.

A PTY is docker exec into this chat's container, with the workspace at /work.
No host bash. Missing Docker is a hard error.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import socket
import time
from typing import Optional

from ui import codebox

IDLE_S = 15 * 60
MAX_SESSIONS = 8
SHELL = "/bin/bash"
_SLOT_RE = re.compile(r"^[A-Za-z0-9._-]{1,16}$")

_sessions: dict[tuple[str, str, str], "ShellSession"] = {}
_gates: dict[tuple[str, str, str], asyncio.Lock] = {}
_lock = asyncio.Lock()


class ShellError(RuntimeError):
    pass


def docker_bin() -> str:
    try:
        return codebox.docker_bin()
    except codebox.CodeboxError as exc:
        raise ShellError(str(exc)) from exc


def jail_command(username: str, chat_id: str, workspace) -> list[str]:
    """docker run argv that can only see this chat's project folder as /work."""
    from pathlib import Path

    return codebox.run_args(username, chat_id, Path(workspace))


def slot_name(raw: str = "") -> str:
    text = str(raw or "1").strip()[:16]
    return text if _SLOT_RE.fullmatch(text) else "1"


def session_key(username: str, chat_id: str, slot: str = "") -> tuple[str, str, str]:
    return (username, chat_id, slot_name(slot))


class ShellSession:
    def __init__(self, username: str, chat_id: str, slot: str = "1") -> None:
        self.username = username
        self.chat_id = chat_id
        self.slot = slot_name(slot)
        self.sock = None
        self.exec_id = ""
        self._pending = b""
        self.last_io = time.time()

    async def start(self) -> None:
        try:
            await asyncio.to_thread(codebox.ensure_container, self.username, self.chat_id)
            exec_id = await asyncio.to_thread(
                codebox.create_exec, self.username, self.chat_id, [SHELL], True
            )
            sock, pending = await asyncio.to_thread(codebox.start_exec_tty, exec_id)
        except codebox.CodeboxError as exc:
            raise ShellError(str(exc)) from exc
        except FileNotFoundError as exc:
            raise ShellError("install docker") from exc
        except OSError as exc:
            raise ShellError(str(exc)) from exc
        self.exec_id = exec_id
        self.sock = sock
        self._pending = pending
        self.last_io = time.time()

    async def write(self, data: bytes) -> None:
        if self.sock is None or not data:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.sock_sendall(self.sock, data)
            self.last_io = time.time()
        except OSError:
            self.close()

    def resize(self, cols: int, rows: int) -> None:
        if not self.exec_id:
            return
        codebox.resize_exec(self.exec_id, cols, rows)

    async def read(self, n: int = 4096) -> bytes:
        if self._pending:
            chunk = self._pending[:n]
            self._pending = self._pending[n:]
            self.last_io = time.time()
            return chunk
        if self.sock is None:
            return b""
        loop = asyncio.get_running_loop()
        try:
            chunk = await loop.sock_recv(self.sock, n)
        except OSError:
            self.close()
            return b""
        if chunk:
            self.last_io = time.time()
            return chunk
        self.close()
        return b""

    def alive(self) -> bool:
        return self.sock is not None and bool(self.exec_id)

    def idle(self) -> bool:
        return time.time() - self.last_io > IDLE_S

    def close(self) -> None:
        sock = self.sock
        self.sock = None
        self.exec_id = ""
        self._pending = b""
        if sock is not None:
            with contextlib.suppress(Exception):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(Exception):
                sock.close()


def connection_gate(username: str, chat_id: str, slot: str = "") -> asyncio.Lock:
    """One shell websocket at a time per chat slot, so close/reopen cannot overlap."""
    key = session_key(username, chat_id, slot)
    lock = _gates.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _gates[key] = lock
    return lock


async def get_session(username: str, chat_id: str, slot: str = "") -> ShellSession:
    """Start a new PTY for this websocket. Closing the UI pane must not reuse a
    half-dead exec: the new xterm would be blank and look broken."""
    key = session_key(username, chat_id, slot)
    async with _lock:
        dead = [item for item, session in _sessions.items() if not session.alive() or session.idle()]
        for item in dead:
            _sessions.pop(item).close()
        old = _sessions.pop(key, None)
        if old:
            old.close()
        if len(_sessions) >= MAX_SESSIONS:
            oldest = next(iter(_sessions))
            _sessions.pop(oldest).close()
        session = ShellSession(username, chat_id, key[2])
        _sessions[key] = session
    try:
        await session.start()
    except BaseException:
        async with _lock:
            if _sessions.get(key) is session:
                _sessions.pop(key, None)
        session.close()
        raise
    return session


async def release_session(
    username: str, chat_id: str, session: ShellSession, slot: str = ""
) -> None:
    key = session_key(username, chat_id, slot or getattr(session, "slot", ""))
    async with _lock:
        if _sessions.get(key) is session:
            _sessions.pop(key, None)
        session.close()


def drop_chat(username: str, chat_id: str) -> None:
    dead = [key for key in list(_sessions) if key[0] == username and key[1] == chat_id]
    for key in dead:
        session = _sessions.pop(key, None)
        if session:
            session.close()
    codebox.drop_container(username, chat_id)


def drop_user(username: str) -> None:
    dead = [key for key in list(_sessions) if key[0] == username]
    for key in dead:
        session = _sessions.pop(key, None)
        if session:
            session.close()

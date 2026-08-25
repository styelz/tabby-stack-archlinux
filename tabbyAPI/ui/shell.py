"""Jailed project shell for UI Code mode.

A PTY runs only inside bubblewrap, with the chat workspace bound at /work.
No host bash. Missing bwrap is a hard error.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import shutil
import signal
import struct
import termios
import time
from pathlib import Path
from typing import Optional

from ui.workspace import workspace_root

IDLE_S = 15 * 60
MAX_SESSIONS = 8
SHELL = "/bin/bash"

_sessions: dict[tuple[str, str], "ShellSession"] = {}
_lock = asyncio.Lock()


class ShellError(RuntimeError):
    pass


def bwrap_bin() -> str:
    path = shutil.which("bwrap")
    if not path:
        raise ShellError("install bubblewrap")
    return path


def jail_command(workspace: Path) -> list[str]:
    """bwrap argv that can only see this chat's project folder as /work."""
    root = workspace.resolve()
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)
    cmd = [
        bwrap_bin(),
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-uts",
        "--hostname",
        "tabby",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(root),
        "/work",
        "--chdir",
        "/work",
        "--setenv",
        "HOME",
        "/work",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "TERM",
        "xterm-256color",
        "--setenv",
        "PS1",
        "\\W $ ",
    ]
    for host, dest in (
        ("/usr", "/usr"),
        ("/bin", "/bin"),
        ("/lib", "/lib"),
        ("/lib64", "/lib64"),
        ("/etc/resolv.conf", "/etc/resolv.conf"),
        ("/etc/ssl", "/etc/ssl"),
        ("/etc/ca-certificates", "/etc/ca-certificates"),
        ("/etc/nsswitch.conf", "/etc/nsswitch.conf"),
        ("/etc/passwd", "/etc/passwd"),
        ("/etc/group", "/etc/group"),
    ):
        if Path(host).exists():
            cmd.extend(["--ro-bind", host, dest])
    cmd.append(SHELL)
    return cmd


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    cols = max(20, min(int(cols or 80), 400))
    rows = max(4, min(int(rows or 24), 120))
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
    except OSError:
        pass


class ShellSession:
    def __init__(self, username: str, chat_id: str) -> None:
        self.username = username
        self.chat_id = chat_id
        self.master: Optional[int] = None
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.last_io = time.time()
        self.readers: list = []

    async def start(self) -> None:
        root = workspace_root(self.username, self.chat_id, create=True)
        cmd = jail_command(root)
        master, slave = os.openpty()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            os.close(master)
            os.close(slave)
            raise ShellError("install bubblewrap") from exc
        except OSError as exc:
            os.close(master)
            os.close(slave)
            raise ShellError(str(exc)) from exc
        os.close(slave)
        os.set_blocking(master, False)
        self.master = master
        self.last_io = time.time()

    def write(self, data: bytes) -> None:
        if self.master is None:
            return
        try:
            os.write(self.master, data)
            self.last_io = time.time()
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        if self.master is None:
            return
        _set_winsize(self.master, cols, rows)

    async def read(self, n: int = 4096) -> bytes:
        if self.master is None:
            return b""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()

        def _ready() -> None:
            if future.done():
                return
            try:
                chunk = os.read(self.master, n)
            except BlockingIOError:
                return
            except OSError:
                chunk = b""
            future.set_result(chunk)

        loop.add_reader(self.master, _ready)
        try:
            chunk = await future
        finally:
            with contextlib.suppress(Exception):
                loop.remove_reader(self.master)
        if chunk:
            self.last_io = time.time()
        return chunk

    def alive(self) -> bool:
        return bool(self.proc and self.proc.returncode is None and self.master is not None)

    def idle(self) -> bool:
        return time.time() - self.last_io > IDLE_S

    def close(self) -> None:
        proc = self.proc
        self.proc = None
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(proc.pid, signal.SIGTERM)
            with contextlib.suppress(ProcessLookupError, OSError):
                proc.kill()
        if self.master is not None:
            with contextlib.suppress(OSError):
                os.close(self.master)
            self.master = None


async def get_session(username: str, chat_id: str) -> ShellSession:
    key = (username, chat_id)
    async with _lock:
        dead = [item for item, session in _sessions.items() if not session.alive() or session.idle()]
        for item in dead:
            _sessions.pop(item).close()
        session = _sessions.get(key)
        if session and session.alive():
            return session
        if session:
            session.close()
        if len(_sessions) >= MAX_SESSIONS:
            oldest = next(iter(_sessions))
            _sessions.pop(oldest).close()
        session = ShellSession(username, chat_id)
        await session.start()
        _sessions[key] = session
        return session


def drop_chat(username: str, chat_id: str) -> None:
    session = _sessions.pop((username, chat_id), None)
    if session:
        session.close()

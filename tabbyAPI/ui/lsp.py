"""Host language-server proxy for UI Code mode.

One JSON-RPC process per (user, chat, language). Spawn only binaries already
on PATH. cwd is the jailed chat workspace. Missing servers are a quiet skip.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional
from ui.workspace import is_text_path, resolve_rel, workspace_root

IDLE_S = 10 * 60
MAX_SERVERS = 16

_SUFFIX_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".json": "json",
}

_COMMANDS: dict[str, list[list[str]]] = {
    "python": [["pylsp"], ["pyright-langserver", "--stdio"]],
    "javascript": [["typescript-language-server", "--stdio"]],
    "typescript": [["typescript-language-server", "--stdio"]],
    "html": [["vscode-html-language-server", "--stdio"]],
    "css": [["vscode-css-language-server", "--stdio"]],
    "json": [["vscode-json-language-server", "--stdio"]],
}

_servers: dict[tuple[str, str, str], "LspServer"] = {}
_lock = asyncio.Lock()


def language_for(path: str) -> str:
    suffix = Path(str(path or "")).suffix.lower()
    return _SUFFIX_LANG.get(suffix, "")


def _bin_search_path() -> str:
    root = Path(__file__).resolve().parent.parent
    extra = [
        root / "venv" / "bin",
        root / ".lsp-tools" / "node_modules" / ".bin",
    ]
    parts = [str(path) for path in extra if path.is_dir()]
    parts.append(os.environ.get("PATH") or "")
    return os.pathsep.join(parts)


def which_bin(name: str) -> Optional[str]:
    return shutil.which(name, path=_bin_search_path())


def command_for(language: str) -> Optional[list[str]]:
    for argv in _COMMANDS.get(language, []):
        found = which_bin(argv[0]) if argv else None
        if found:
            return [found, *argv[1:]]
    return None


def file_uri(root: Path, rel: str) -> str:
    dest = resolve_rel(root, rel)
    return dest.resolve().as_uri()


def uri_to_rel(root: Path, uri: str) -> str:
    text = str(uri or "")
    if text.startswith("file://"):
        text = text[7:]
        if text.startswith("/") and os.name == "nt":
            text = text.lstrip("/")
    try:
        path = Path(text)
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return ""


class LspServer:
    def __init__(self, username: str, chat_id: str, language: str, argv: list[str]) -> None:
        self.username = username
        self.chat_id = chat_id
        self.language = language
        self.argv = argv
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.root: Optional[Path] = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._buf = b""
        self.last_io = time.time()
        self.ready = asyncio.Event()
        self._reader_task: Optional[asyncio.Task] = None
        self.listeners: list = []

    async def start(self) -> None:
        self.root = workspace_root(self.username, self.chat_id, create=True)
        self.proc = await asyncio.create_subprocess_exec(
            *self.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self.root),
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        root_uri = self.root.resolve().as_uri()
        result = await self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "workspaceFolders": [{"uri": root_uri, "name": "project"}],
                "capabilities": {
                    "textDocument": {
                        "synchronization": {"didSave": True, "dynamicRegistration": False},
                        "completion": {"completionItem": {"snippetSupport": False}},
                        "hover": {"contentFormat": ["plaintext", "markdown"]},
                        "publishDiagnostics": {},
                    }
                },
            },
        )
        await self.notify("initialized", {})
        self.ready.set()
        self.last_io = time.time()
        return result

    def _pack(self, payload: dict[str, Any]) -> bytes:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body

    async def notify(self, method: str, params: Any) -> None:
        if not self.proc or not self.proc.stdin:
            return
        self.proc.stdin.write(self._pack({"jsonrpc": "2.0", "method": method, "params": params}))
        await self.proc.stdin.drain()
        self.last_io = time.time()

    async def request(self, method: str, params: Any, timeout: float = 8.0) -> Any:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("Language server is not running.")
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = future
        self.proc.stdin.write(
            self._pack({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        )
        await self.proc.stdin.drain()
        self.last_io = time.time()
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(req_id, None)

    async def _read_loop(self) -> None:
        stdout = self.proc.stdout if self.proc else None
        if stdout is None:
            return
        try:
            while True:
                chunk = await stdout.read(4096)
                if not chunk:
                    break
                self._buf += chunk
                self.last_io = time.time()
                self._drain()
        except (asyncio.CancelledError, OSError):
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Language server closed."))
            self._pending.clear()

    def _drain(self) -> None:
        while True:
            header_end = self._buf.find(b"\r\n\r\n")
            if header_end < 0:
                return
            headers = self._buf[:header_end].decode("ascii", "replace")
            length = 0
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    try:
                        length = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        length = 0
            start = header_end + 4
            if len(self._buf) < start + length:
                return
            body = self._buf[start : start + length]
            self._buf = self._buf[start + length :]
            try:
                message = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            self._dispatch(message)

    def _dispatch(self, message: dict[str, Any]) -> None:
        if "id" in message and "method" not in message:
            req_id = message.get("id")
            future = self._pending.get(req_id) if isinstance(req_id, int) else None
            if future and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(str(message.get("error"))))
                else:
                    future.set_result(message.get("result"))
            return
        method = str(message.get("method") or "")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "textDocument/publishDiagnostics":
            uri = str(params.get("uri") or "")
            rel = uri_to_rel(self.root, uri) if self.root else ""
            items = params.get("diagnostics") if isinstance(params.get("diagnostics"), list) else []
            event = {"type": "diagnostics", "path": rel, "items": items}
            for listener in list(self.listeners):
                listener(event)

    def alive(self) -> bool:
        return bool(self.proc and self.proc.returncode is None)

    def idle(self) -> bool:
        return time.time() - self.last_io > IDLE_S

    def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        proc = self.proc
        self.proc = None
        if proc:
            with contextlib.suppress(ProcessLookupError, OSError):
                proc.kill()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("Language server closed."))
        self._pending.clear()
        self.listeners.clear()


async def get_server(username: str, chat_id: str, language: str) -> Optional[LspServer]:
    if not language:
        return None
    argv = command_for(language)
    if not argv:
        return None
    key = (username, chat_id, language)
    async with _lock:
        dead = [item for item, server in _servers.items() if not server.alive() or server.idle()]
        for item in dead:
            _servers.pop(item).close()
        server = _servers.get(key)
        if server and server.alive():
            return server
        if server:
            server.close()
        if len(_servers) >= MAX_SERVERS:
            oldest = next(iter(_servers))
            _servers.pop(oldest).close()
        server = LspServer(username, chat_id, language, argv)
        try:
            await server.start()
        except Exception:
            server.close()
            return None
        _servers[key] = server
        return server


def drop_chat(username: str, chat_id: str) -> None:
    dead = [key for key in _servers if key[0] == username and key[1] == chat_id]
    for key in dead:
        _servers.pop(key).close()


async def handle_client(username: str, chat_id: str, message: dict[str, Any]) -> Optional[dict[str, Any]]:
    kind = str(message.get("type") or "")
    path = str(message.get("path") or "")
    if kind == "probe":
        language = language_for(path) or str(message.get("language") or "")
        argv = command_for(language) if language else None
        return {
            "type": "probe",
            "language": language,
            "command": argv[0] if argv else "",
            "available": bool(argv),
        }
    if not path or not is_text_path(path):
        return {"type": "error", "message": "Unsupported path."}
    language = language_for(path)
    if not language:
        return {"type": "unavailable", "path": path, "language": ""}
    server = await get_server(username, chat_id, language)
    if not server or not server.root:
        return {"type": "unavailable", "path": path, "language": language}
    uri = file_uri(server.root, path)
    text = message.get("text") if isinstance(message.get("text"), str) else ""
    if kind == "didOpen":
        await server.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language,
                    "version": int(message.get("version") or 1),
                    "text": text,
                }
            },
        )
        return {"type": "opened", "path": path, "language": language}
    if kind == "didChange":
        await server.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": int(message.get("version") or 1)},
                "contentChanges": [{"text": text}],
            },
        )
        return None
    if kind == "didClose":
        await server.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
        return None
    if kind == "didSave":
        await server.notify(
            "textDocument/didSave",
            {"textDocument": {"uri": uri}, "text": text},
        )
        return None
    line = max(0, int(message.get("line") or 0))
    character = max(0, int(message.get("character") or 0))
    pos = {"line": line, "character": character}
    if kind == "completion":
        result = await server.request(
            "textDocument/completion",
            {"textDocument": {"uri": uri}, "position": pos},
        )
        items = result.get("items") if isinstance(result, dict) else result
        if not isinstance(items, list):
            items = []
        labels = []
        for item in items[:80]:
            if isinstance(item, dict) and item.get("label"):
                labels.append(
                    {
                        "label": str(item.get("label")),
                        "detail": str(item.get("detail") or ""),
                        "insert": str(item.get("insertText") or item.get("label")),
                    }
                )
        return {"type": "completion", "id": message.get("id"), "path": path, "items": labels}
    if kind == "hover":
        result = await server.request(
            "textDocument/hover",
            {"textDocument": {"uri": uri}, "position": pos},
        )
        contents = ""
        if isinstance(result, dict):
            raw = result.get("contents")
            if isinstance(raw, str):
                contents = raw
            elif isinstance(raw, dict):
                contents = str(raw.get("value") or "")
            elif isinstance(raw, list) and raw:
                first = raw[0]
                contents = first if isinstance(first, str) else str((first or {}).get("value") or "")
        return {"type": "hover", "id": message.get("id"), "path": path, "contents": contents}
    return {"type": "error", "message": f"Unknown LSP request {kind!r}."}

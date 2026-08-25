"""Short-lived tokens that let a browser load a Code-mode project as a site.

The session cookie cannot be used here. Preview pages are served under a CSP
sandbox so LLM-written HTML gets an opaque origin instead of the console's
origin, and a sandboxed document does not send SameSite=Lax cookies with its
own subresource requests. The token sits in the path instead, so relative
``src`` and ``href`` values resolve back onto an authorized URL.

That opaque origin also makes ``window.localStorage`` throw. Generated pages
often persist into it, so HTML responses get an in-memory shim. Do not add
``allow-same-origin``: that would give the page the console origin.
"""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from typing import Optional

TOKEN_TTL_S = 2 * 60 * 60
MAX_TOKENS = 200
# No allow-same-origin: the page must not reach the console DOM or its cookies.
SANDBOX_CSP = (
    "sandbox allow-scripts allow-forms allow-modals allow-popups "
    "allow-top-navigation-by-user-activation"
)
_STORAGE_MARK = "data-tabby-preview-storage"
_STORAGE_SHIM = (
    f'<script {_STORAGE_MARK}="1">'
    "(function(){"
    "function memoryStorage(){"
    "var data=Object.create(null),keys=[];"
    "return{"
    "getItem:function(key){"
    "key=String(key);"
    "return Object.prototype.hasOwnProperty.call(data,key)?data[key]:null;"
    "},"
    "setItem:function(key,value){"
    "key=String(key);"
    "if(!Object.prototype.hasOwnProperty.call(data,key))keys.push(key);"
    "data[key]=String(value);"
    "},"
    "removeItem:function(key){"
    "key=String(key);"
    "if(Object.prototype.hasOwnProperty.call(data,key)){"
    "delete data[key];keys=Object.keys(data);"
    "}"
    "},"
    "clear:function(){data=Object.create(null);keys=[];},"
    "key:function(i){return keys[i]==null?null:keys[i];},"
    "get length(){return keys.length;}"
    "};"
    "}"
    "function install(name){"
    "try{void window[name];return;}catch(err){}"
    "try{"
    "Object.defineProperty(window,name,{"
    "configurable:true,enumerable:true,value:memoryStorage()"
    "});"
    "}catch(err){}"
    "}"
    'install("localStorage");'
    'install("sessionStorage");'
    "})();"
    "</script>"
)

_tokens: dict[str, dict] = {}
_lock = threading.Lock()


def _prune(now: float) -> None:
    dead = [key for key, row in _tokens.items() if now - row["created_at"] > TOKEN_TTL_S]
    for key in dead:
        _tokens.pop(key, None)
    if len(_tokens) <= MAX_TOKENS:
        return
    oldest = sorted(_tokens.items(), key=lambda item: item[1]["created_at"])
    for key, _row in oldest[: len(_tokens) - MAX_TOKENS]:
        _tokens.pop(key, None)


def mint(username: str, chat_id: str) -> str:
    """Reuse a live token for this chat so a reload keeps the same URL."""
    now = time.time()
    with _lock:
        _prune(now)
        for key, row in _tokens.items():
            if row["username"] == username and row["chat_id"] == chat_id:
                row["created_at"] = now
                return key
        token = secrets.token_urlsafe(24)
        _tokens[token] = {"username": username, "chat_id": chat_id, "created_at": now}
        return token


def resolve(token: str) -> Optional[tuple[str, str]]:
    if not token:
        return None
    now = time.time()
    with _lock:
        _prune(now)
        row = _tokens.get(token)
        if not row:
            return None
        # Sliding window: an open preview tab keeps working while it is in use.
        row["created_at"] = now
        return row["username"], row["chat_id"]


def drop_chat(username: str, chat_id: str) -> None:
    with _lock:
        dead = [
            key
            for key, row in _tokens.items()
            if row["username"] == username and row["chat_id"] == chat_id
        ]
        for key in dead:
            _tokens.pop(key, None)


def drop_user(username: str) -> None:
    with _lock:
        dead = [key for key, row in _tokens.items() if row["username"] == username]
        for key in dead:
            _tokens.pop(key, None)


def is_html_name(name: str) -> bool:
    return Path(name).suffix.lower() in {".html", ".htm"}


def inject_storage_shim(html: str) -> str:
    """Put in-memory Storage on sandboxed previews before page scripts run."""
    if _STORAGE_MARK in html:
        return html
    lower = html.lower()
    for tag in ("<head", "<html"):
        start = lower.find(tag)
        if start == -1:
            continue
        end = html.find(">", start)
        if end == -1:
            continue
        return html[: end + 1] + _STORAGE_SHIM + html[end + 1 :]
    return _STORAGE_SHIM + html


def html_preview_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8", errors="replace")
    return inject_storage_shim(text).encode("utf-8")

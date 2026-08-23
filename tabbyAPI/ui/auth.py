"""Linux-user login for the management UI.

Validates the stack account via PAM (in a subprocess) and issues an
HTTP-only session cookie. Never call libpam inside the API process —
a bad ctypes conversation used to abort TabbyAPI with free(): invalid size.
"""

from __future__ import annotations

import getpass
import os
import secrets
import subprocess
import sys
import threading
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Request, Response

COOKIE_NAME = "tabby_ui"
SESSION_TTL_S = 24 * 60 * 60
LOGIN_WINDOW_S = 60
LOGIN_MAX_ATTEMPTS = 5
PAM_CHECK_TIMEOUT_S = 15

_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()
_login_hits: dict[str, list[float]] = {}
_login_lock = threading.Lock()
_AUTHENTICATE = None


def stack_username() -> str:
    env = (os.environ.get("TABBY_UI_USER") or "").strip()
    if env:
        return env
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def _pam_authenticate(username: str, password: str) -> bool:
    """Ask a throwaway helper process. Crash there must not kill TabbyAPI."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ui.pam_check", username],
            input=password.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PAM_CHECK_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def is_admin_username(username: str) -> bool:
    expected = stack_username()
    return bool(expected) and username == expected


def authenticate_user(username: str, password: str) -> bool:
    if not username or not password:
        return False
    expected = stack_username()
    if expected and username == expected:
        if _AUTHENTICATE is not None:
            return bool(_AUTHENTICATE(username, password))
        return _pam_authenticate(username, password)
    from ui.users import verify_extra_user

    return verify_extra_user(username, password)


def set_authenticator(fn) -> None:
    global _AUTHENTICATE
    _AUTHENTICATE = fn


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _sessions_lock:
        _sessions[token] = {
            "username": username,
            "is_admin": is_admin_username(username),
            "created_at": now,
            "last_activity": now,
        }
    return token


def validate_session(token: str, max_age: int = SESSION_TTL_S) -> Optional[str]:
    if not token:
        return None
    now = time.time()
    with _sessions_lock:
        session = _sessions.get(token)
        if not session:
            return None
        if now - session["last_activity"] > max_age:
            _sessions.pop(token, None)
            return None
        session["last_activity"] = now
        return session["username"]


def destroy_session(token: str) -> None:
    with _sessions_lock:
        _sessions.pop(token, None)


def destroy_sessions_for_user(username: str) -> None:
    if not username:
        return
    with _sessions_lock:
        dead = [token for token, session in _sessions.items() if session.get("username") == username]
        for token in dead:
            _sessions.pop(token, None)


def clear_sessions() -> None:
    with _sessions_lock:
        _sessions.clear()
    with _login_lock:
        _login_hits.clear()


def login_allowed(ip: str) -> bool:
    now = time.time()
    with _login_lock:
        hits = [stamp for stamp in _login_hits.get(ip, []) if now - stamp < LOGIN_WINDOW_S]
        _login_hits[ip] = hits
        return len(hits) < LOGIN_MAX_ATTEMPTS


def record_login_attempt(ip: str) -> None:
    now = time.time()
    with _login_lock:
        hits = [stamp for stamp in _login_hits.get(ip, []) if now - stamp < LOGIN_WINDOW_S]
        hits.append(now)
        _login_hits[ip] = hits


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def set_session_cookie(response: Response, token: str, request: Request | None = None) -> None:
    secure = False
    if request is not None:
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
        secure = proto == "https"
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=SESSION_TTL_S,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def require_ui_user(
    request: Request,
    tabby_ui: Optional[str] = Cookie(None, alias=COOKIE_NAME),
) -> str:
    username = validate_session(tabby_ui or "")
    if username:
        return username
    raise HTTPException(401, "Not authenticated")


async def require_ui_admin(
    request: Request,
    tabby_ui: Optional[str] = Cookie(None, alias=COOKIE_NAME),
) -> str:
    username = await require_ui_user(request, tabby_ui)
    if not is_admin_username(username):
        raise HTTPException(403, "Admin only.")
    return username

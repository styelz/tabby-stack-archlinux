"""Linux-user login for the management UI.

Validates the stack account via PAM and issues an HTTP-only session cookie.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import getpass
import os
import secrets
import threading
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Request, Response

COOKIE_NAME = "tabby_ui"
SESSION_TTL_S = 24 * 60 * 60
LOGIN_WINDOW_S = 60
LOGIN_MAX_ATTEMPTS = 5

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
    try:
        import pam  # type: ignore

        return bool(pam.pam().authenticate(username, password))
    except Exception:
        pass

    libname = ctypes.util.find_library("pam") or "libpam.so.0"
    try:
        libpam = ctypes.CDLL(libname)
    except OSError:
        return False

    class PamHandle(ctypes.Structure):
        _fields_ = [("handle", ctypes.c_void_p)]

    class PamMessage(ctypes.Structure):
        _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]

    class PamResponse(ctypes.Structure):
        _fields_ = [("resp", ctypes.c_char_p), ("resp_retcode", ctypes.c_int)]

    conv_func = ctypes.CFUNCTYPE(
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.POINTER(PamMessage)),
        ctypes.POINTER(ctypes.POINTER(PamResponse)),
        ctypes.c_void_p,
    )

    class PamConv(ctypes.Structure):
        _fields_ = [("conv", conv_func), ("appdata_ptr", ctypes.c_void_p)]

    PAM_PROMPT_ECHO_OFF = 1
    PAM_SUCCESS = 0
    password_bytes = password.encode("utf-8")

    def conv(n_msg, msg, resp, _app):
        try:
            libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
            libc.strdup.restype = ctypes.c_char_p
            array_type = PamResponse * n_msg
            replies = array_type()
            for index in range(n_msg):
                style = msg[index].contents.msg_style
                if style == PAM_PROMPT_ECHO_OFF:
                    replies[index].resp = libc.strdup(password_bytes)
                    replies[index].resp_retcode = 0
                else:
                    replies[index].resp = None
                    replies[index].resp_retcode = 0
            resp[0] = ctypes.cast(replies, ctypes.POINTER(PamResponse))
            return PAM_SUCCESS
        except Exception:
            return 2

    conversation = PamConv(conv_func(conv), None)
    handle = PamHandle()
    start = libpam.pam_start
    start.restype = ctypes.c_int
    start.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.POINTER(PamConv),
        ctypes.POINTER(PamHandle),
    ]
    status = start(
        b"login",
        username.encode("utf-8"),
        ctypes.byref(conversation),
        ctypes.byref(handle),
    )
    if status != PAM_SUCCESS:
        return False
    auth = libpam.pam_authenticate
    auth.restype = ctypes.c_int
    ok = auth(handle, 0) == PAM_SUCCESS
    libpam.pam_end(handle, 0)
    return bool(ok)


def authenticate_user(username: str, password: str) -> bool:
    if _AUTHENTICATE is not None:
        return bool(_AUTHENTICATE(username, password))
    expected = stack_username()
    if not expected or username != expected:
        return False
    if not password:
        return False
    return _pam_authenticate(username, password)


def set_authenticator(fn) -> None:
    global _AUTHENTICATE
    _AUTHENTICATE = fn


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _sessions_lock:
        _sessions[token] = {
            "username": username,
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

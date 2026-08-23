"""PAM password check for the management UI.

Runs only in a short-lived subprocess so a bad libpam/ctypes interaction
cannot abort the TabbyAPI process (see free(): invalid size).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys


def _pam_authenticate(username: str, password: str, service: str) -> bool:
    libname = ctypes.util.find_library("pam") or "libpam.so.0"
    cname = ctypes.util.find_library("c") or "libc.so.6"
    try:
        libpam = ctypes.CDLL(libname)
        libc = ctypes.CDLL(cname)
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
    password_b = password.encode("utf-8")

    # PAM frees the response array and each resp string with free(3).
    # Allocate both with the C allocator. Never let ctypes treat strdup's
    # return as a Python bytes object (that double-frees).
    libc.calloc.restype = ctypes.c_void_p
    libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    libc.strdup.restype = ctypes.c_void_p
    libc.strdup.argtypes = [ctypes.c_char_p]

    @conv_func
    def conv(n_msg, msg, resp, _app):
        if n_msg <= 0:
            return 2
        raw = libc.calloc(n_msg, ctypes.sizeof(PamResponse))
        if not raw:
            return 2
        resp[0] = ctypes.cast(raw, ctypes.POINTER(PamResponse))
        for index in range(n_msg):
            style = msg[index].contents.msg_style
            if style == PAM_PROMPT_ECHO_OFF:
                dup = libc.strdup(password_b)
                if not dup:
                    return 2
                resp[0][index].resp = ctypes.cast(dup, ctypes.c_char_p)
            else:
                resp[0][index].resp = None
            resp[0][index].resp_retcode = 0
        return PAM_SUCCESS

    # Keep the callback alive until pam_end returns.
    conversation = PamConv(conv, None)
    handle = PamHandle()

    pam_start = libpam.pam_start
    pam_start.restype = ctypes.c_int
    pam_start.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.POINTER(PamConv),
        ctypes.POINTER(PamHandle),
    ]
    pam_authenticate = libpam.pam_authenticate
    pam_authenticate.restype = ctypes.c_int
    pam_authenticate.argtypes = [PamHandle, ctypes.c_int]
    pam_acct_mgmt = libpam.pam_acct_mgmt
    pam_acct_mgmt.restype = ctypes.c_int
    pam_acct_mgmt.argtypes = [PamHandle, ctypes.c_int]
    pam_end = libpam.pam_end
    pam_end.restype = ctypes.c_int
    pam_end.argtypes = [PamHandle, ctypes.c_int]

    status = pam_start(
        service.encode("utf-8"),
        username.encode("utf-8"),
        ctypes.byref(conversation),
        ctypes.byref(handle),
    )
    if status != PAM_SUCCESS:
        return False
    status = pam_authenticate(handle, 0)
    if status == PAM_SUCCESS:
        status = pam_acct_mgmt(handle, 0)
    pam_end(handle, status)
    # Prevent premature GC of the callback while PAM still holds it.
    _ = conversation
    return status == PAM_SUCCESS


def authenticate(username: str, password: str) -> bool:
    if not username or password is None:
        return False
    try:
        import pam  # type: ignore

        return bool(pam.pam().authenticate(username, password))
    except Exception:
        pass
    for service in ("login", "system-auth", "su"):
        try:
            if _pam_authenticate(username, password, service):
                return True
        except Exception:
            continue
    return False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: pam_check <username>", file=sys.stderr)
        return 2
    username = args[0]
    password = sys.stdin.read()
    if password.endswith("\n"):
        password = password[:-1]
    if password.endswith("\r"):
        password = password[:-1]
    return 0 if authenticate(username, password) else 1


if __name__ == "__main__":
    raise SystemExit(main())

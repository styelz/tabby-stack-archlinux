"""Tabby-only UI accounts (not Linux users). Admin is the stack Linux account."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PBKDF2_ROUNDS = 200_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
MIN_PASSWORD = 8

_LOCK = threading.Lock()
_USERS_PATH: Optional[Path] = None

ROOT = Path(__file__).resolve().parent.parent


def users_path() -> Path:
    if _USERS_PATH is not None:
        return _USERS_PATH
    return ROOT / "ui_users.json"


def set_users_path(path: Optional[Path]) -> None:
    global _USERS_PATH
    _USERS_PATH = path


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    )
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, rounds_s, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if kind != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return secrets.compare_digest(digest, expected)


def _load() -> dict[str, Any]:
    path = users_path()
    if not path.is_file():
        return {"users": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"users": []}
    if not isinstance(data, dict) or not isinstance(data.get("users"), list):
        return {"users": []}
    return data


def _save(data: dict[str, Any]) -> None:
    path = users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _stack_name() -> str:
    from ui.auth import stack_username

    return (stack_username() or "").strip()


def normalize_username(name: str) -> str:
    return str(name or "").strip()


def validate_username(name: str) -> str:
    username = normalize_username(name)
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 3–32 characters: letters, digits, dot, underscore, hyphen."
        )
    stack = _stack_name()
    if stack and username.lower() == stack.lower():
        raise ValueError("That username is the Linux admin account.")
    return username


def get_user(username: str) -> Optional[dict[str, Any]]:
    wanted = normalize_username(username).lower()
    if not wanted:
        return None
    with _LOCK:
        for user in _load().get("users") or []:
            if not isinstance(user, dict):
                continue
            if str(user.get("username") or "").lower() == wanted:
                return user
    return None


def list_users() -> list[dict[str, str]]:
    with _LOCK:
        rows = []
        for user in _load().get("users") or []:
            if not isinstance(user, dict):
                continue
            name = str(user.get("username") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "username": name,
                    "created_at": str(user.get("created_at") or ""),
                }
            )
        rows.sort(key=lambda item: item["username"].lower())
        return rows


def _logins_map(data: dict[str, Any]) -> dict[str, int]:
    raw = data.get("logins")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            out[name] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return out


def _login_count_from(logins: dict[str, int], username: str) -> int:
    wanted = normalize_username(username).lower()
    if not wanted:
        return 0
    for name, count in logins.items():
        if name.lower() == wanted:
            return count
    return 0


def record_login(username: str) -> int:
    """Count a successful UI login for extra users and the Linux admin."""
    name = normalize_username(username)
    if not name:
        return 0
    with _LOCK:
        data = _load()
        canonical = name
        for user in data.get("users") or []:
            if not isinstance(user, dict):
                continue
            stored = str(user.get("username") or "").strip()
            if stored.lower() == name.lower():
                canonical = stored
                break
        logins = _logins_map(data)
        count = 0
        for existing in list(logins):
            if existing.lower() == canonical.lower():
                count = logins.pop(existing)
        count += 1
        logins[canonical] = count
        data["logins"] = logins
        _save(data)
        return count


def list_accounts() -> list[dict[str, Any]]:
    """Admin plus extra users, with login / chat / image counts for the Users page."""
    from common.gallery_owners import image_counts
    from ui.chats import chat_count

    stack = _stack_name()
    with _LOCK:
        data = _load()
        logins = _logins_map(data)
        extras: list[dict[str, Any]] = []
        for user in data.get("users") or []:
            if not isinstance(user, dict):
                continue
            name = str(user.get("username") or "").strip()
            if not name:
                continue
            extras.append(
                {
                    "username": name,
                    "created_at": str(user.get("created_at") or ""),
                    "is_admin": False,
                    "logins": _login_count_from(logins, name),
                }
            )
        extras.sort(key=lambda item: item["username"].lower())
    owned, untagged = image_counts()

    def images_for(name: str, is_admin: bool) -> int:
        total = 0
        wanted = name.lower()
        for owner, count in owned.items():
            if str(owner).lower() == wanted:
                total += count
        if is_admin:
            total += untagged
        return total

    rows: list[dict[str, Any]] = []
    if stack:
        rows.append(
            {
                "username": stack,
                "created_at": "",
                "is_admin": True,
                "logins": _login_count_from(logins, stack),
                "chats": chat_count(stack),
                "images": images_for(stack, True),
            }
        )
    for extra in extras:
        name = str(extra["username"])
        extra["chats"] = chat_count(name)
        extra["images"] = images_for(name, False)
        rows.append(extra)
    return rows


def create_user(username: str, password: str) -> dict[str, str]:
    username = validate_username(username)
    if not password or len(password) < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
    with _LOCK:
        data = _load()
        users = [u for u in (data.get("users") or []) if isinstance(u, dict)]
        if any(str(u.get("username") or "").lower() == username.lower() for u in users):
            raise ValueError("That username already exists.")
        record = {
            "username": username,
            "password_hash": hash_password(password),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        users.append(record)
        data["users"] = users
        _save(data)
    return {"username": username, "created_at": record["created_at"]}


def set_password(username: str, password: str) -> None:
    username = normalize_username(username)
    if not username:
        raise KeyError("User not found.")
    if not password or len(password) < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
    with _LOCK:
        data = _load()
        users = [u for u in (data.get("users") or []) if isinstance(u, dict)]
        found = False
        for user in users:
            if str(user.get("username") or "").lower() == username.lower():
                user["password_hash"] = hash_password(password)
                found = True
                break
        if not found:
            raise KeyError("User not found.")
        data["users"] = users
        _save(data)


def delete_user(username: str) -> None:
    username = normalize_username(username)
    if not username:
        raise KeyError("User not found.")
    stack = _stack_name()
    if stack and username.lower() == stack.lower():
        raise ValueError("Cannot delete the Linux admin account.")
    with _LOCK:
        data = _load()
        users = [u for u in (data.get("users") or []) if isinstance(u, dict)]
        kept = [
            u
            for u in users
            if str(u.get("username") or "").lower() != username.lower()
        ]
        if len(kept) == len(users):
            raise KeyError("User not found.")
        data["users"] = kept
        logins = data.get("logins")
        if isinstance(logins, dict):
            drop = [
                key
                for key in logins
                if str(key).lower() == username.lower()
            ]
            for key in drop:
                logins.pop(key, None)
            data["logins"] = logins
        _save(data)


def verify_extra_user(username: str, password: str) -> bool:
    if not username or not password:
        return False
    user = get_user(username)
    if not user:
        return False
    return verify_password(password, str(user.get("password_hash") or ""))

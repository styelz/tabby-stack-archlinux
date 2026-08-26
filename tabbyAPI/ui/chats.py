"""Per-user console chat history stored next to generated images."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.Lock()
_CHATS_DIR: Optional[Path] = None
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

EMPTY_STORE = {
    "version": 1,
    "activeId": "",
    "chats": [],
    "lastByMode": {"chat": "", "code": ""},
}
PLACEHOLDER_TITLES = frozenset({"", "New chat", "New workspace"})


def chats_dir() -> Path:
    if _CHATS_DIR is not None:
        return _CHATS_DIR
    from common.gpu_mode import GENERATED_DIR

    path = GENERATED_DIR / "ui_chats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_chats_dir(path: Optional[Path]) -> None:
    global _CHATS_DIR
    _CHATS_DIR = path


def _safe_name(username: str) -> str:
    name = SAFE_NAME_RE.sub("_", str(username or "").strip()) or "user"
    return name[:80]


def chat_path(username: str) -> Path:
    return chats_dir() / f"{_safe_name(username)}.json"


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _collapse_key(chat: dict[str, Any]) -> Optional[tuple[str, int]]:
    if str(chat.get("mode") or "") != "code":
        return None
    if str(chat.get("parentId") or "").strip():
        return None
    title = str(chat.get("title") or "").strip()
    if title in PLACEHOLDER_TITLES:
        return None
    try:
        stamp = int(chat.get("updatedAt") or 0)
    except (TypeError, ValueError):
        stamp = 0
    return (title, stamp)


def _collapse_duplicate_workspaces(
    chats: list[dict[str, Any]], protect: Optional[set[str]] = None
) -> list[dict[str, Any]]:
    """Keep one Code workspace per (title, updatedAt) and drop empty New-chat shells."""
    guarded = {item for item in (protect or set()) if item}
    kids: dict[str, list[dict[str, Any]]] = {}
    for chat in chats:
        parent = str(chat.get("parentId") or "").strip()
        if parent:
            kids.setdefault(parent, []).append(chat)
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for chat in chats:
        key = _collapse_key(chat)
        if key is None:
            continue
        groups.setdefault(key, []).append(chat)
    remap: dict[str, str] = {}
    drop: set[str] = set()
    for roots in groups.values():
        if len(roots) < 2:
            continue
        with_kids = [root for root in roots if root["id"] in kids]
        kept = (with_kids or roots)[0]
        for root in roots:
            if root["id"] == kept["id"]:
                continue
            drop.add(root["id"])
            remap[root["id"]] = kept["id"]
    for chat in chats:
        if chat["id"] in drop:
            continue
        title = str(chat.get("title") or "").strip()
        if (
            chat.get("mode") == "code"
            and not str(chat.get("parentId") or "").strip()
            and title in PLACEHOLDER_TITLES
            and chat["id"] not in kids
            and chat["id"] not in guarded
        ):
            drop.add(chat["id"])
    for chat in chats:
        parent = str(chat.get("parentId") or "").strip()
        if parent in remap:
            chat["parentId"] = remap[parent]
    return [chat for chat in chats if chat["id"] not in drop]


def _remap_collapsed_id(raw: Any, cleaned: list[dict[str, Any]], wanted: str) -> str:
    want = str(wanted or "").strip()
    if not want:
        return ""
    ids = {chat["id"] for chat in cleaned}
    if want in ids:
        return want
    incoming = raw.get("chats") if isinstance(raw, dict) else None
    if not isinstance(incoming, list):
        return ""
    match = next(
        (
            item
            for item in incoming
            if isinstance(item, dict) and str(item.get("id") or "") == want
        ),
        None,
    )
    if not isinstance(match, dict):
        return ""
    parent = str(match.get("parentId") or "").strip()
    if parent:
        if parent in ids:
            return parent
        return _remap_collapsed_id(raw, cleaned, parent)
    title = str(match.get("title") or "").strip()
    if title in PLACEHOLDER_TITLES:
        return ""
    try:
        stamp = int(match.get("updatedAt") or 0)
    except (TypeError, ValueError):
        stamp = 0
    for chat in cleaned:
        if _collapse_key(chat) == (title, stamp):
            return chat["id"]
    for chat in cleaned:
        if chat.get("mode") == "code" and not chat.get("parentId"):
            if str(chat.get("title") or "").strip() == title:
                return chat["id"]
    return ""


def _kept_duplicate_root(old: Any, remaining: list[dict[str, Any]]) -> str:
    if not isinstance(old, dict):
        return ""
    title = str(old.get("title") or "").strip()
    if title in PLACEHOLDER_TITLES:
        return ""
    try:
        stamp = int(old.get("updatedAt") or 0)
    except (TypeError, ValueError):
        stamp = 0
    for chat in remaining:
        if _collapse_key(chat) == (title, stamp):
            return str(chat.get("id") or "")
    for chat in remaining:
        if chat.get("mode") == "code" and not chat.get("parentId"):
            if str(chat.get("title") or "").strip() == title:
                return str(chat.get("id") or "")
    return ""


def normalize_store(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "version": 1,
            "activeId": "",
            "chats": [],
            "lastByMode": {"chat": "", "code": ""},
        }
    chats = raw.get("chats")
    if not isinstance(chats, list):
        chats = []
    cleaned = []
    seen: set[str] = set()
    for item in chats:
        if not isinstance(item, dict):
            continue
        chat_id = str(item.get("id") or "").strip()
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        messages = item.get("messages")
        if not isinstance(messages, list):
            messages = []
        mode = str(item.get("mode") or "chat").strip().lower()
        if mode not in ("chat", "code"):
            mode = "chat"
        parent_id = ""
        if mode == "code":
            parent_id = str(item.get("parentId") or "").strip()
            if parent_id == chat_id:
                parent_id = ""
        cleaned.append(
            {
                "id": chat_id,
                "title": str(item.get("title") or "New chat"),
                "updatedAt": int(item.get("updatedAt") or 0),
                "pinned": bool(item.get("pinned")),
                "titleLocked": bool(item.get("titleLocked")),
                "mode": mode,
                "parentId": parent_id,
                "messages": messages,
            }
        )
    roots = {
        chat["id"]
        for chat in cleaned
        if chat["mode"] == "code" and not chat["parentId"]
    }
    cleaned = [
        chat
        for chat in cleaned
        if not chat["parentId"] or chat["parentId"] in roots
    ]
    last_hint = raw.get("lastByMode") if isinstance(raw.get("lastByMode"), dict) else {}
    cleaned = _collapse_duplicate_workspaces(
        cleaned,
        {
            str(raw.get("activeId") or ""),
            str(last_hint.get("code") or ""),
        },
    )
    ids = {chat["id"] for chat in cleaned}
    active = str(raw.get("activeId") or "")
    if active not in ids:
        # A collapsed duplicate root may still be the selected chat.
        active = _remap_collapsed_id(raw, cleaned, active)
    if cleaned and active not in {c["id"] for c in cleaned}:
        active = cleaned[0]["id"]
    if not cleaned:
        active = ""
    version = raw.get("version")
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = 1
    last_raw = raw.get("lastByMode")
    last = last_raw if isinstance(last_raw, dict) else {}
    last_by_mode = {
        "chat": str(last.get("chat") or ""),
        "code": str(last.get("code") or ""),
    }
    if last_by_mode["code"] not in ids:
        last_by_mode["code"] = _remap_collapsed_id(raw, cleaned, last_by_mode["code"])
    if last_by_mode["chat"] not in ids or not any(
        c["id"] == last_by_mode["chat"] and c["mode"] == "chat" for c in cleaned
    ):
        last_by_mode["chat"] = ""
    if last_by_mode["code"] not in ids or not any(
        c["id"] == last_by_mode["code"] and c["mode"] == "code" for c in cleaned
    ):
        last_by_mode["code"] = ""
    return {
        "version": version or 1,
        "activeId": active,
        "chats": cleaned,
        "lastByMode": last_by_mode,
    }


def _read_disk(username: str) -> Any:
    path = chat_path(username)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_store(username: str) -> dict[str, Any]:
    with _LOCK:
        raw = _read_disk(username)
    if raw is None:
        return dict(EMPTY_STORE)
    return normalize_store(raw)


def is_workspace_root(chat: Any) -> bool:
    """True for a Code-mode chat that owns the project folder."""
    if not isinstance(chat, dict):
        return False
    if str(chat.get("mode") or "chat").strip().lower() != "code":
        return False
    return not str(chat.get("parentId") or "").strip()


def workspace_root_chat_id(username: str, chat_id: str) -> str:
    """The Code-mode workspace id that owns this chat's project folder."""
    raw = str(chat_id or "").strip()
    if not raw:
        raise ValueError("Invalid chat id")
    for chat in load_store(username).get("chats") or []:
        if not isinstance(chat, dict):
            continue
        if str(chat.get("id") or "") != raw:
            continue
        parent = str(chat.get("parentId") or "").strip()
        return parent or raw
    return raw


def workspace_thread_ids(username: str, root_id: str) -> list[str]:
    raw = str(root_id or "").strip()
    if not raw:
        return []
    return [
        str(chat.get("id") or "")
        for chat in load_store(username).get("chats") or []
        if isinstance(chat, dict)
        and str(chat.get("parentId") or "").strip() == raw
        and str(chat.get("id") or "").strip()
    ]


def save_store(username: str, raw: Any) -> dict[str, Any]:
    with _LOCK:
        disk = _read_disk(username)
    previous = normalize_store(disk) if disk is not None else dict(EMPTY_STORE)
    store = normalize_store(raw)
    old_chats: dict[str, Any] = {}
    if isinstance(disk, dict) and isinstance(disk.get("chats"), list):
        for item in disk["chats"]:
            if isinstance(item, dict) and str(item.get("id") or "").strip():
                old_chats[str(item.get("id")).strip()] = item
    for chat in previous.get("chats") or []:
        chat_id = str(chat.get("id") or "")
        if chat_id and chat_id not in old_chats:
            old_chats[chat_id] = chat
    new_ids = {str(chat.get("id") or "") for chat in store.get("chats") or []}
    remaining_roots = [
        chat for chat in store.get("chats") or [] if is_workspace_root(chat)
    ]
    dropped = [chat_id for chat_id in old_chats if chat_id not in new_ids]
    payload = json.dumps(store, ensure_ascii=False) + "\n"
    with _LOCK:
        _atomic_write(chat_path(username), payload)
    if dropped:
        from ui import lsp, shell
        from ui.preview import drop_chat
        from ui.workspace import (
            delete_workspace,
            drop_drafts,
            drop_history,
            merge_workspace_dirs,
            safe_name,
        )

        for chat_id in dropped:
            # Nested chats share the parent folder; never wipe it with the thread.
            if not is_workspace_root(old_chats.get(chat_id)):
                continue
            kept = _kept_duplicate_root(old_chats.get(chat_id), remaining_roots)
            if kept:
                merge_workspace_dirs(username, kept, [chat_id])
                drop_history(username, chat_id)
                drop_drafts(username, chat_id)
                continue
            shell.drop_chat(username, chat_id)
            lsp.drop_chat(username, chat_id)
            delete_workspace(username, chat_id)
            drop_chat(username, safe_name(chat_id))
    return store


def chat_count(username: str) -> int:
    """Conversations that have at least one user message."""
    n = 0
    for chat in load_store(username).get("chats") or []:
        messages = chat.get("messages") if isinstance(chat, dict) else None
        if not isinstance(messages, list):
            continue
        if any(
            isinstance(item, dict)
            and item.get("role") == "user"
            and str(item.get("content") or "").strip()
            for item in messages
        ):
            n += 1
    return n


def delete_store(username: str) -> None:
    path = chat_path(username)
    with _LOCK:
        try:
            path.unlink()
        except OSError:
            pass
    from ui import lsp, shell
    from ui.preview import drop_user
    from ui.workspace import delete_user_workspaces

    shell.drop_user(username)
    lsp.drop_user(username)
    delete_user_workspaces(username)
    drop_user(username)

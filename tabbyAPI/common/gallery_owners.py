"""Sidecar map of generated-*.png filename → UI username."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
_OWNERS_PATH: Optional[Path] = None
OWNERS_NAME = "gallery_owners.json"


def owners_path() -> Path:
    if _OWNERS_PATH is not None:
        return _OWNERS_PATH
    from common.gpu_mode import GENERATED_DIR

    return GENERATED_DIR / OWNERS_NAME


def set_owners_path(path: Optional[Path]) -> None:
    global _OWNERS_PATH
    _OWNERS_PATH = path


def _load() -> dict[str, str]:
    path = owners_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        name = str(key or "").strip()
        owner = str(value or "").strip()
        if name and owner:
            out[name] = owner
    return out


def _save(mapping: dict[str, str]) -> None:
    path = owners_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(mapping, indent=2, sort_keys=True) + "\n"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def png_name(name: str) -> str:
    raw = str(name or "").strip()
    if raw.endswith(".jpg"):
        return raw[: -len(".jpg")] + ".png"
    return raw


def owner_of(name: str) -> Optional[str]:
    key = png_name(name)
    with _LOCK:
        owner = _load().get(key)
    return owner or None


def record_owner(name: str, owner: Optional[str]) -> None:
    key = png_name(name)
    username = str(owner or "").strip()
    if not key or not username or key == "generated-latest.png":
        return
    with _LOCK:
        mapping = _load()
        mapping[key] = username
        _save(mapping)


def forget_owners(names: list[str]) -> None:
    keys = {png_name(n) for n in names if n}
    if not keys:
        return
    with _LOCK:
        mapping = _load()
        changed = False
        for key in keys:
            if key in mapping:
                mapping.pop(key, None)
                changed = True
        if changed:
            _save(mapping)


def is_admin_owned(name: str) -> bool:
    return owner_of(name) is None


def can_access(name: str, username: str, is_admin: bool) -> bool:
    if is_admin:
        return True
    owner = owner_of(name)
    return bool(owner) and owner == username


def filter_files(files: list[Path], username: str, is_admin: bool) -> list[Path]:
    if is_admin:
        return list(files)
    return [path for path in files if owner_of(path.name) == username]


def image_counts() -> tuple[dict[str, int], int]:
    """Return (owner → count, untagged count). Untagged files count as admin's."""
    from common.gpu_mode import list_generated_files

    with _LOCK:
        mapping = _load()
    owned: dict[str, int] = {}
    untagged = 0
    for path in list_generated_files():
        owner = mapping.get(png_name(path.name))
        if owner:
            owned[owner] = owned.get(owner, 0) + 1
        else:
            untagged += 1
    return owned, untagged

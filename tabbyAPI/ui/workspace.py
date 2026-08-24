"""Jailed per-user, per-chat project folder for UI Code mode."""

from __future__ import annotations

import io
import mimetypes
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Optional

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
# Editing is limited to what the console can safely round-trip as UTF-8 text.
TEXT_SUFFIXES = frozenset(
    {
        ".html",
        ".htm",
        ".css",
        ".js",
        ".mjs",
        ".json",
        ".jsx",
        ".ts",
        ".tsx",
        ".md",
        ".txt",
        ".svg",
        ".xml",
        ".yml",
        ".yaml",
        ".csv",
        ".py",
        ".sh",
        ".php",
        ".toml",
        ".ini",
        ".conf",
    }
)
PAGE_SUFFIXES = frozenset({".html", ".htm"})
MAX_FILES = 200
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_TEXT_BYTES = 1 * 1024 * 1024

_WORK_DIR: Optional[Path] = None


def workspaces_dir() -> Path:
    if _WORK_DIR is not None:
        return _WORK_DIR
    from common.gpu_mode import GENERATED_DIR

    path = GENERATED_DIR / "ui_workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_workspaces_dir(path: Optional[Path]) -> None:
    global _WORK_DIR
    _WORK_DIR = path


def safe_name(raw: str) -> str:
    # Dots survive the character filter, so a chat id of "." or ".." would
    # otherwise land on the parent folder and reach another chat's files.
    name = SAFE_NAME_RE.sub("_", str(raw or "").strip())[:80]
    if not name or set(name) <= {"."}:
        return "user"
    return name


def user_dir(username: str) -> Path:
    return workspaces_dir() / safe_name(username)


def workspace_root(username: str, chat_id: str, *, create: bool = False) -> Path:
    root = user_dir(username) / safe_name(chat_id)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_rel(root: Path, rel: str) -> Path:
    text = str(rel or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or text.startswith("~"):
        raise ValueError("Invalid path")
    path = Path(text)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("Invalid path")
    parts = [part for part in path.parts if part not in ("", ".")]
    if not parts:
        raise ValueError("Invalid path")
    base = root.resolve()
    dest = (base.joinpath(*parts)).resolve()
    if dest != base and base not in dest.parents:
        raise ValueError("Invalid path")
    return dest


def _is_inside(root: Path, path: Path) -> bool:
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


def _iter_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if _is_inside(root, path):
            out.append(path)
    return out


def _stats(root: Path) -> tuple[int, int]:
    files = _iter_files(root)
    return len(files), sum(path.stat().st_size for path in files)


def _check_caps(root: Path, *, extra_bytes: int = 0, extra_files: int = 0) -> None:
    count, total = _stats(root)
    if count + extra_files > MAX_FILES:
        raise ValueError("This chat's project has too many files.")
    if total + extra_bytes > MAX_TOTAL_BYTES:
        raise ValueError("This chat's project is too large.")


def is_text_path(rel: str) -> bool:
    return Path(str(rel or "")).suffix.lower() in TEXT_SUFFIXES


def list_files(username: str, chat_id: str) -> list[dict[str, Any]]:
    root = workspace_root(username, chat_id, create=False)
    rows: list[dict[str, Any]] = []
    for path in _iter_files(root):
        rel = path.relative_to(root.resolve()).as_posix()
        suffix = path.suffix.lower()
        rows.append(
            {
                "path": rel,
                "size": path.stat().st_size,
                "kind": "image" if suffix in IMAGE_SUFFIXES else "text",
                "editable": suffix in TEXT_SUFFIXES,
                "page": suffix in PAGE_SUFFIXES,
            }
        )
    return rows


def site_entry(username: str, chat_id: str, wanted: str = "") -> str:
    """Pick the page a preview link should land on. Empty when there is none."""
    pages = [row["path"] for row in list_files(username, chat_id) if row["page"]]
    if not pages:
        return ""
    ask = str(wanted or "").strip().lstrip("/")
    if ask in pages:
        return ask
    if "index.html" in pages:
        return "index.html"
    return sorted(pages, key=lambda page: (page.count("/"), page))[0]


def listing(username: str, chat_id: str) -> dict[str, Any]:
    files = list_files(username, chat_id)
    return {
        "files": files,
        "bytes": sum(int(row["size"]) for row in files),
        "count": len(files),
    }


def resolve_file(username: str, chat_id: str, rel: str) -> Path:
    root = workspace_root(username, chat_id, create=False)
    path = resolve_rel(root, rel)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(rel)
    return path


def read_bytes(username: str, chat_id: str, rel: str) -> tuple[Path, bytes]:
    path = resolve_file(username, chat_id, rel)
    return path, path.read_bytes()


def read_text(username: str, chat_id: str, rel: str) -> str:
    _path, data = read_bytes(username, chat_id, rel)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return f"[binary {len(data)} bytes]"


def write_text(username: str, chat_id: str, rel: str, contents: str) -> str:
    text = contents if isinstance(contents, str) else str(contents or "")
    data = text.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError("File is larger than 1 MB.")
    root = workspace_root(username, chat_id, create=True)
    path = resolve_rel(root, rel)
    extra_files = 0 if path.is_file() else 1
    extra_bytes = len(data) - (path.stat().st_size if path.is_file() else 0)
    _check_caps(root, extra_bytes=max(0, extra_bytes), extra_files=extra_files)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.chmod(path, 0o600)
    return path.relative_to(root.resolve()).as_posix()


def str_replace(username: str, chat_id: str, rel: str, old: str, new: str) -> str:
    text = read_text(username, chat_id, rel)
    if old not in text:
        raise ValueError(f"{rel}: old_string was not found.")
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{rel}: old_string must match exactly once ({count} found).")
    write_text(username, chat_id, rel, text.replace(old, new, 1))
    return rel


def delete_file(username: str, chat_id: str, rel: str) -> None:
    root = workspace_root(username, chat_id, create=False)
    path = resolve_rel(root, rel)
    if not path.is_file():
        raise FileNotFoundError(rel)
    path.unlink()
    parent = path.parent
    base = root.resolve()
    while parent != base and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def copy_bytes(username: str, chat_id: str, rel: str, data: bytes) -> str:
    raw = data if isinstance(data, (bytes, bytearray)) else bytes(data or b"")
    root = workspace_root(username, chat_id, create=True)
    path = resolve_rel(root, rel)
    extra_files = 0 if path.is_file() else 1
    extra_bytes = len(raw) - (path.stat().st_size if path.is_file() else 0)
    _check_caps(root, extra_bytes=max(0, extra_bytes), extra_files=extra_files)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    return path.relative_to(root.resolve()).as_posix()


def copy_job_pngs(username: str, chat_id: str, job) -> list[str]:
    from common.gpu_mode import generated_image_path
    from images.paths import generated_png_name_from_url, living_download_pairs

    copied: list[str] = []
    for url, dest in living_download_pairs(job):
        name = generated_png_name_from_url(url)
        src = generated_image_path(name)
        if src is None:
            continue
        copied.append(copy_bytes(username, chat_id, dest, src.read_bytes()))
    return copied


def delete_workspace(username: str, chat_id: str) -> None:
    root = workspace_root(username, chat_id, create=False)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def delete_user_workspaces(username: str) -> None:
    folder = user_dir(username)
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def zip_bytes(username: str, chat_id: str) -> bytes:
    root = workspace_root(username, chat_id, create=False)
    files = _iter_files(root)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arc = path.relative_to(root.resolve()).as_posix()
            zf.write(path, arcname=arc)
    return buf.getvalue()


def guess_media_type(path: Path) -> str:
    guessed, _enc = mimetypes.guess_type(path.name)
    if guessed:
        # Files here are written as UTF-8; say so or a preview mangles accents.
        if guessed.startswith("text/") or guessed in (
            "application/javascript",
            "application/json",
            "image/svg+xml",
        ):
            return f"{guessed}; charset=utf-8"
        return guessed
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return "application/octet-stream"
    return "text/plain; charset=utf-8"

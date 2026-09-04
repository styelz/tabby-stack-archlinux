"""Per-user zip backup of chats, Code workspaces, prefs, and gallery images."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FORMAT = "tabby-stack-user-backup"
VERSION = 1
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
PNG_NAME_RE = re.compile(r"^generated-[A-Za-z0-9._-]+\.png$")
THUMB_NAME_RE = re.compile(r"^generated-[A-Za-z0-9._-]+\.jpg$")
UPLOAD_MAX_BYTES = 32 * 1024 * 1024 * 1024
UNCOMPRESSED_MAX = 32 * 1024 * 1024 * 1024
MAX_MEMBERS = 100_000


class BackupError(ValueError):
    pass


def safe_name(username: str) -> str:
    name = SAFE_NAME_RE.sub("_", str(username or "").strip()) or "user"
    if set(name) <= {"."}:
        return "user"
    return name[:80]


def archive_filename(username: str, when: Optional[datetime] = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"tabby-backup-{safe_name(username)}-{stamp}.zip"


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    if path.is_symlink() or not path.is_file():
        return
    zf.write(path, arcname.replace("\\", "/"))


def _add_tree(zf: zipfile.ZipFile, root: Path, prefix: str) -> int:
    if not root.is_dir() or root.is_symlink():
        return 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name for name in dirnames if not Path(dirpath, name).is_symlink()
        ]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            _add_file(zf, path, f"{prefix}/{rel}")
            count += 1
    return count


def _owned_gallery_files(username: str, *, include_untagged: bool) -> list[Path]:
    from common.gallery_owners import owner_of, png_name
    from common.gpu_mode import list_generated_files

    out: list[Path] = []
    for path in list_generated_files():
        if path.name == "generated-latest.png":
            continue
        owner = owner_of(png_name(path.name))
        if owner == username or (include_untagged and not owner):
            out.append(path)
    return out


def build_archive(
    username: str,
    dest: Path,
    *,
    include_untagged: bool = False,
) -> Path:
    from common.gpu_mode import GENERATED_DIR
    from ui.chats import EMPTY_STORE, chat_path
    from ui.prefs import EMPTY_PREFS, prefs_path
    from ui.workspace import user_dir

    user = str(username or "").strip()
    if not user:
        raise BackupError("Username is required")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    chats_file = chat_path(user)
    prefs_file = prefs_path(user)
    work = user_dir(user)
    gallery = _owned_gallery_files(user, include_untagged=include_untagged)
    owners = {path.name: user for path in gallery}

    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "username": user,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "chats": True,
            "prefs": True,
            "workspace": work.is_dir(),
            "gallery": len(gallery),
        },
    }
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )
            if chats_file.is_file() and not chats_file.is_symlink():
                _add_file(zf, chats_file, "chats.json")
            else:
                zf.writestr(
                    "chats.json",
                    json.dumps(EMPTY_STORE, ensure_ascii=False) + "\n",
                )
            if prefs_file.is_file() and not prefs_file.is_symlink():
                _add_file(zf, prefs_file, "prefs.json")
            else:
                zf.writestr(
                    "prefs.json",
                    json.dumps(EMPTY_PREFS, ensure_ascii=False) + "\n",
                )
            _add_tree(zf, work, "workspace")
            zf.writestr(
                "gallery_owners.json",
                json.dumps(owners, indent=2, sort_keys=True) + "\n",
            )
            thumbs = GENERATED_DIR / "thumbs"
            for path in gallery:
                _add_file(zf, path, f"gallery/{path.name}")
                thumb = thumbs / f"{path.stem}.jpg"
                _add_file(zf, thumb, f"gallery/thumbs/{thumb.name}")
        os.replace(tmp, dest)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return dest


def _zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def _safe_extract_path(root: Path, name: str) -> Path:
    rel = str(name or "").replace("\\", "/").lstrip("/")
    if not rel or rel.endswith("/"):
        raise BackupError("Invalid backup path")
    if rel.startswith("/") or rel.startswith("\\"):
        raise BackupError("Invalid backup path")
    parts = Path(rel).parts
    if ".." in parts or any(part in (".", "") for part in parts):
        raise BackupError("Invalid backup path")
    dest = (root / rel).resolve()
    try:
        dest.relative_to(root.resolve())
    except ValueError as exc:
        raise BackupError("Invalid backup path") from exc
    return dest


def _extract_zip(src: Path, staging: Path) -> dict[str, Any]:
    try:
        zf = zipfile.ZipFile(src, "r")
    except zipfile.BadZipFile as exc:
        raise BackupError("Not a valid backup zip") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise BackupError("Backup has too many files")
        total = 0
        for info in infos:
            if info.is_dir():
                continue
            if _zip_symlink(info):
                raise BackupError("Backup contains a symlink")
            total += max(0, int(info.file_size or 0))
            if total > UNCOMPRESSED_MAX:
                raise BackupError("Backup is too large")
        if "manifest.json" not in zf.namelist():
            raise BackupError("Backup is missing manifest.json")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BackupError("Backup manifest is invalid") from exc
        if not isinstance(manifest, dict):
            raise BackupError("Backup manifest is invalid")
        if manifest.get("format") != FORMAT:
            raise BackupError("Not a Tabby user backup")
        try:
            version = int(manifest.get("version") or 0)
        except (TypeError, ValueError) as exc:
            raise BackupError("Backup version is invalid") from exc
        if version != VERSION:
            raise BackupError("Unsupported backup version")
        for info in infos:
            name = str(info.filename or "").replace("\\", "/")
            if info.is_dir() or name.endswith("/"):
                continue
            dest = _safe_extract_path(staging, name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src_fh, open(dest, "wb") as out:
                shutil.copyfileobj(src_fh, out)
    return manifest


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise BackupError(f"Invalid {path.name}") from exc


def _unique_gallery_name(name: str) -> str:
    from common.gpu_mode import GENERATED_DIR

    if not (GENERATED_DIR / name).exists():
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    for i in range(1, 10_000):
        candidate = f"{stem}-restored{i}{suffix}"
        if not (GENERATED_DIR / candidate).exists():
            return candidate
    raise BackupError("Could not find a free gallery filename")


def _clear_user_gallery(username: str, *, include_untagged: bool) -> None:
    from common.gpu_mode import delete_generated_images

    names = [
        path.name
        for path in _owned_gallery_files(username, include_untagged=include_untagged)
    ]
    if names:
        delete_generated_images(names, delete_all=False)


def _restore_gallery(username: str, staging: Path) -> int:
    from common.gallery_owners import record_owner
    from common.gpu_mode import GENERATED_DIR

    folder = staging / "gallery"
    if not folder.is_dir():
        return 0
    thumbs_src = folder / "thumbs"
    thumbs_dest = GENERATED_DIR / "thumbs"
    count = 0
    for path in sorted(folder.iterdir()):
        if path.is_dir() or path.is_symlink() or not path.is_file():
            continue
        if not PNG_NAME_RE.match(path.name) or path.name == "generated-latest.png":
            continue
        dest_name = _unique_gallery_name(path.name)
        dest = GENERATED_DIR / dest_name
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        os.chmod(dest, 0o644)
        record_owner(dest_name, username)
        thumb = thumbs_src / f"{path.stem}.jpg"
        if thumb.is_file() and not thumb.is_symlink() and THUMB_NAME_RE.match(thumb.name):
            thumbs_dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(thumb, thumbs_dest / f"{Path(dest_name).stem}.jpg")
        count += 1
    return count


def _replace_user_workspace(username: str, staging: Path) -> None:
    from ui.workspace import delete_user_workspaces, user_dir

    delete_user_workspaces(username)
    src = staging / "workspace"
    dest = user_dir(username)
    if not src.is_dir():
        return
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest, symlinks=False, dirs_exist_ok=False)


def restore_archive(
    username: str,
    src: Path,
    *,
    include_untagged: bool = False,
) -> dict[str, Any]:
    from ui.chats import EMPTY_STORE, chat_path, normalize_store
    from ui.prefs import EMPTY_PREFS, normalize_prefs, prefs_path

    user = str(username or "").strip()
    if not user:
        raise BackupError("Username is required")
    src = Path(src)
    if not src.is_file():
        raise BackupError("Backup file is missing")
    size = src.stat().st_size
    if size <= 0:
        raise BackupError("Backup file is empty")
    if size > UPLOAD_MAX_BYTES:
        raise BackupError("Backup is too large")

    staging = Path(tempfile.mkdtemp(prefix="tabby-restore-"))
    try:
        manifest = _extract_zip(src, staging)
        chats_file = staging / "chats.json"
        prefs_file = staging / "prefs.json"
        chats_raw = _load_json(chats_file) if chats_file.is_file() else dict(EMPTY_STORE)
        prefs_raw = _load_json(prefs_file) if prefs_file.is_file() else dict(EMPTY_PREFS)
        store = normalize_store(chats_raw)
        prefs = normalize_prefs(prefs_raw)
        _clear_user_gallery(user, include_untagged=include_untagged)
        _replace_user_workspace(user, staging)
        _atomic_write(chat_path(user), json.dumps(store, ensure_ascii=False) + "\n")
        _atomic_write(prefs_path(user), json.dumps(prefs, ensure_ascii=False) + "\n")
        images = _restore_gallery(user, staging)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "ok": True,
        "username": user,
        "source_username": str(manifest.get("username") or ""),
        "gallery": images,
    }

"""Save pasted chat images to disk so they can be copied, not rewritten as text."""

from __future__ import annotations

import base64
import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from common.logger import xlogger
from endpoints.OAI.types.chat_completion import ChatCompletionRequest

ROOT = Path(__file__).resolve().parent.parent
SAVE_DIR = ROOT / "pasted-images"
LATEST = SAVE_DIR / "latest.png"
WORKSPACE = Path.home()
MAX_SAVED_IMAGES = 200
DATA_URI_RE = re.compile(
    r"^data:(?P<mime>[\w/+.-]+)(?:;charset=[\w-]+)?;base64,(?P<data>.+)$",
    re.I | re.S,
)
SAVE_COMMAND_RE = re.compile(
    r"(?is)(?:"
    r"(?:save|export|write)\s+(?:this|the|that|it)\s+(?:pasted\s+)?"
    r"(?:image|screenshot|picture|photo|png)"
    r"|(?:save|export)\s+(?:the\s+)?(?:pasted\s+)?"
    r"(?:image|screenshot|picture|photo)\s+(?:to|as|into)"
    r"|(?:save|export)\s+(?:this|it)\s+(?:to|as)\s+\S+"
    r")"
)
DEST_FILE_RE = re.compile(
    r"""(?ix)
    (
        (?:[A-Za-z]:[\\/]|~[\\/]|\.{0,2}[\\/])[^\s`'\"<>|]+
        | [\w.-]+
    )
    \.(?:png|jpe?g|webp|gif|bmp)
    """
)
MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",
    b"BM",
)


def is_real_image(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if len(raw) < 32:
        return False
    return raw.startswith(IMAGE_MAGIC)


def _decode_data_uri(url: str) -> Optional[tuple[bytes, str]]:
    match = DATA_URI_RE.match((url or "").strip())
    if not match:
        return None
    try:
        data = base64.b64decode(match.group("data"), validate=False)
    except Exception:
        return None
    if len(data) < 32:
        return None
    mime = match.group("mime").lower()
    ext = MIME_EXT.get(mime, ".png")
    return data, ext


def _iter_image_urls(data: ChatCompletionRequest):
    for message in data.messages or []:
        content = message.content
        if not isinstance(content, list):
            continue
        for part in content:
            if getattr(part, "type", None) != "image_url":
                continue
            image = getattr(part, "image_url", None)
            url = getattr(image, "url", None) if image is not None else None
            if url:
                yield url


def _latest_alias(ext: str) -> Path:
    """Stable name the clipboard hint points at, matching the real format."""
    return LATEST if ext == ".png" else LATEST.with_suffix(ext)


def materialize_pasted_images(data: ChatCompletionRequest) -> list[Path]:
    """Write image_url data URIs from this request to pasted-images/.

    Clients resend the whole history every turn, so the same paste arrives
    again and again. Content-addressed names mean a repeat is recognised
    instead of piling up a new copy per turn.
    """
    saved: list[Path] = []
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    for index, url in enumerate(_iter_image_urls(data), start=1):
        decoded = _decode_data_uri(url)
        if not decoded:
            continue
        raw, ext = decoded
        digest = hashlib.sha256(raw).hexdigest()[:16]
        dest = SAVE_DIR / f"{stamp}-{index}-{digest}{ext}"
        existing = next(SAVE_DIR.glob(f"*-{digest}{ext}"), None)
        if existing is not None:
            dest = existing
        else:
            dest.write_bytes(raw)
            xlogger.info(f"Saved pasted image to {dest} ({len(raw)} bytes)")
        # Only ever put bytes of the matching format behind latest.<ext>.
        # Writing a JPEG into latest.png made the clipboard hint hand out a
        # mislabelled file.
        alias = _latest_alias(ext)
        if not alias.exists() or alias.read_bytes() != raw:
            shutil.copyfile(dest, alias)
        saved.append(dest)
    prune_saved_images()
    return saved


def prune_saved_images(keep: int = MAX_SAVED_IMAGES) -> list[Path]:
    """Drop the oldest pastes so the folder cannot grow without bound."""
    aliases = {LATEST.name} | {LATEST.with_suffix(ext).name for ext in MIME_EXT.values()}
    files = [
        path
        for path in SAVE_DIR.glob("*")
        if path.is_file() and path.name not in aliases and path.suffix.lower() in MIME_EXT.values()
    ]
    if len(files) <= keep:
        return []
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    removed = []
    for path in files[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    if removed:
        xlogger.info(f"Pruned {len(removed)} old pasted images from {SAVE_DIR}")
    return removed


def latest_image() -> Optional[Path]:
    if is_real_image(LATEST):
        return LATEST
    if not SAVE_DIR.exists():
        return None
    newest = None
    newest_mtime = 0.0
    for path in SAVE_DIR.iterdir():
        if path.is_file() and is_real_image(path):
            mtime = path.stat().st_mtime
            if mtime > newest_mtime:
                newest = path
                newest_mtime = mtime
    return newest


def resolve_save_dest(text: str, workspace: Path | None = None) -> Path:
    root = workspace or WORKSPACE
    # Last filename wins: "save the screenshot to notes.png" mentions the
    # destination after the source.
    matches = list(DEST_FILE_RE.finditer(text or ""))
    match = matches[-1] if matches else None
    if match:
        raw = match.group(0).strip().strip("`\"'")
        dest = Path(raw).expanduser()
        if not dest.is_absolute():
            dest = root / dest
    elif re.search(r"(?i)\bworkspace\b", text or ""):
        dest = root / "pasted-image.png"
    else:
        dest = root / "pasted-image.png"

    dest = dest.resolve()
    try:
        dest.relative_to(Path.home().resolve())
    except ValueError:
        dest = root / dest.name
    if dest.suffix.lower() not in MIME_EXT.values():
        dest = dest.with_suffix(".png")
    return dest


def is_save_image_request(text: str) -> bool:
    return bool(SAVE_COMMAND_RE.search(text or ""))


def pasted_public_name(path: Optional[Path] = None) -> str:
    """Filename under /v1/images/pasted/ for the latest paste."""
    source = path or latest_image()
    if source is None:
        return "latest.png"
    if source.name.startswith("latest"):
        return source.name
    if source.suffix.lower() in (".jpg", ".jpeg"):
        return "latest.jpg"
    return "latest.png"


def pasted_image_path(name: str) -> Optional[Path]:
    """Resolve a safe file under pasted-images/ for the HTTP gallery."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    if name in ("latest", "latest.png"):
        path = LATEST
    elif name in ("latest.jpg", "latest.jpeg"):
        path = LATEST.with_suffix(".jpg")
        if not path.is_file() and LATEST.with_suffix(".jpeg").is_file():
            path = LATEST.with_suffix(".jpeg")
    else:
        path = SAVE_DIR / name
    try:
        path = path.resolve()
        root = SAVE_DIR.resolve()
    except OSError:
        return None
    if path.parent != root or not path.is_file():
        return None
    if path.suffix.lower() not in MIME_EXT.values():
        return None
    return path


def pasted_download_text(text: str, api_base: str) -> str:
    """Tell a remote client how to fetch the paste. Do not write on the GPU host."""
    source = latest_image()
    if source is None:
        return (
            "No pasted image file was found. Paste the image in the same message, "
            "then ask to save it."
        )
    dest = resolve_save_dest(text)
    url = f"{api_base.rstrip('/')}/images/pasted/{pasted_public_name(source)}"
    return (
        "The pasted image is on this API host, not this workspace. "
        f"It is at:\n{url}\n"
        f"Use that URL when you need the file as {dest.name}."
    )


def save_requested_image(text: str, workspace: Path | None = None) -> tuple[Optional[Path], str]:
    """Local-admin copy onto this machine. Remote clients should use pasted_download_text."""
    source = latest_image()
    if source is None:
        return None, (
            "No pasted image file was found. Paste the image in the same message, "
            "then ask to save it."
        )
    dest = resolve_save_dest(text, workspace)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    size = dest.stat().st_size
    return dest, f"Saved the pasted image to {dest} ({size} bytes)."

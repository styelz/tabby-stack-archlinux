"""Static files for the management UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_SUFFIXES = {".css", ".js", ".html", ".svg", ".png", ".ico", ".woff2", ".map"}


def static_file(name: str) -> Path:
    if not name or name != Path(name).name:
        raise HTTPException(400, "Invalid asset name")
    path = (STATIC_DIR / name).resolve()
    if not str(path).startswith(str(STATIC_DIR.resolve())):
        raise HTTPException(400, "Invalid asset path")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(404, "Unknown asset")
    if not path.is_file():
        raise HTTPException(404, "Asset not found")
    return path


def file_response(name: str) -> FileResponse:
    path = static_file(name)
    media = {
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".map": "application/json",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media)

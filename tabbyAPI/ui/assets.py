"""Static files for the management UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_SUFFIXES = {
    ".css",
    ".js",
    ".html",
    ".svg",
    ".png",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
}


def static_file(name: str, *, nested: bool = False) -> Path:
    if not name:
        raise HTTPException(400, "Invalid asset name")
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(400, "Invalid asset path")
    if not nested and name != rel.name:
        raise HTTPException(400, "Invalid asset name")
    path = (STATIC_DIR / rel).resolve()
    root = STATIC_DIR.resolve()
    if path != root and root not in path.parents:
        raise HTTPException(400, "Invalid asset path")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(404, "Unknown asset")
    if not path.is_file():
        raise HTTPException(404, "Asset not found")
    return path


def file_response(name: str, *, nested: bool = False) -> FileResponse:
    path = static_file(name, nested=nested)
    media = {
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".map": "application/json",
    }.get(path.suffix.lower(), "application/octet-stream")
    response = FileResponse(path, media_type=media)
    # Management UI assets change often; avoid sticky browser/proxy caches
    # that leave empty working bubbles after a status-line fix.
    if path.suffix.lower() in {".css", ".js", ".html"}:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

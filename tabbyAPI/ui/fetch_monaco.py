#!/usr/bin/env python3
"""Download monaco-editor min/vs into ui/static/vs (not committed)."""

from __future__ import annotations

import io
import shutil
import tarfile
import urllib.request
from pathlib import Path

VERSION = "0.52.2"
URL = f"https://registry.npmjs.org/monaco-editor/-/monaco-editor-{VERSION}.tgz"
DEST = Path(__file__).resolve().parent / "static" / "vs"
PREFIX = "package/min/vs/"


def present() -> bool:
    return (DEST / "loader.js").is_file() and (DEST / "editor" / "editor.main.js").is_file()


def fetch(force: bool = False) -> Path:
    if present() and not force:
        return DEST
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=180) as resp:
        data = resp.read()
    tmp = DEST.parent / "vs.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if not name.startswith(PREFIX):
                continue
            rel = name[len(PREFIX) :]
            if not rel or ".." in Path(rel).parts:
                continue
            dest = tmp / rel
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(extracted.read())
    if DEST.exists():
        shutil.rmtree(DEST)
    tmp.rename(DEST)
    return DEST


if __name__ == "__main__":
    path = fetch()
    print(f"monaco {VERSION} -> {path}")

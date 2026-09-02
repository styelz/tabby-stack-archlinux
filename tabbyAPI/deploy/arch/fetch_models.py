#!/usr/bin/env python3
"""Copy or Hugging Face–download installer weights. Skip anything already on disk."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

SHARD_RE = re.compile(r"^(?P<stem>.+)-(?P<index>\d{5})-of-(?P<total>\d{5})\.safetensors$")
INCOMPLETE_GLOBS = (
    "*.incomplete",
    "*.part",
    ".cache/huggingface/download/**/*.incomplete",
)


def load_catalog(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def select_ids(catalog: dict, model_set: str) -> list[str]:
    sets = catalog.get("sets") or {}
    if model_set not in sets:
        known = ", ".join(sorted(sets)) or "(none)"
        raise SystemExit(f"Unknown model set {model_set!r}. Use one of: {known}")
    return list(sets[model_set])


def dest_path(item: dict, tabby: Path, comfy: Path) -> Path:
    rel = item["dest"]
    if rel.startswith("tabby/"):
        return tabby / rel[len("tabby/") :]
    if rel.startswith("comfy/"):
        return comfy / rel[len("comfy/") :]
    raise SystemExit(f"dest must start with tabby/ or comfy/: {rel}")


def has_incomplete_downloads(dest: Path) -> bool:
    """True when an earlier interrupted run left partial files behind."""
    return any(next(dest.glob(pattern), None) is not None for pattern in INCOMPLETE_GLOBS)


def shards_complete(dest: Path) -> bool | None:
    """Whether every shard of a split safetensors model is present.

    Returns None when the folder is not sharded, so the caller falls back to
    the catalog's marker files. A single shard of a two-part model must not
    count as a finished download.
    """
    groups: dict[tuple[str, int], set[int]] = {}
    for path in dest.glob("*-of-*.safetensors"):
        match = SHARD_RE.match(path.name)
        if match and path.stat().st_size > 0:
            key = (match.group("stem"), int(match.group("total")))
            groups.setdefault(key, set()).add(int(match.group("index")))
    if not groups:
        return None
    return all(seen == set(range(1, total + 1)) for (_, total), seen in groups.items())


def is_ready(dest: Path, item: dict) -> bool:
    if item.get("kind") == "file":
        return dest.is_file() and dest.stat().st_size > 0
    if not dest.is_dir():
        return False
    if has_incomplete_downloads(dest):
        return False
    if shards_complete(dest) is False:
        return False
    for name in item.get("ready") or []:
        found = dest / name
        if found.is_file() and found.stat().st_size > 0:
            return True
    return any(dest.glob("model*.safetensors"))


def find_cache(item: dict, cache_root: Path | None) -> Path | None:
    if cache_root is None:
        return None
    for rel in item.get("cache") or []:
        candidate = cache_root / rel
        if item.get("kind") == "file":
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        elif candidate.is_dir() and is_ready(candidate, item):
            return candidate
    return None


def fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(n)} B"


def note(msg: str) -> None:
    print(msg, flush=True)


def copy_file_logged(src: str, dst: str, *, follow_symlinks: bool = True) -> str:
    src_path = Path(src)
    size = src_path.stat().st_size if src_path.is_file() else 0
    note(f"      {src_path.name} ({fmt_bytes(size)})")
    return shutil.copy2(src, dst, follow_symlinks=follow_symlinks)


def verify_tree(src: Path, dest: Path) -> None:
    """Fail loudly when a folder copy dropped or truncated a file."""
    for path in src.rglob("*"):
        parts = path.relative_to(src).parts
        if not path.is_file() or ".cache" in parts or "__pycache__" in parts:
            continue
        mirror = dest / path.relative_to(src)
        if not mirror.is_file() or mirror.stat().st_size != path.stat().st_size:
            raise SystemExit(f"incomplete copy: {mirror} does not match {path}")


def copy_from_cache(src: Path, dest: Path, kind: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if kind == "file":
        note(f"      {src.name} ({fmt_bytes(src.stat().st_size)}) -> {dest}")
        # Land the bytes on a temp name and rename, so an interrupted copy
        # cannot leave a truncated file that is_ready() accepts forever.
        tmp = dest.with_name(f".{dest.name}.part")
        tmp.unlink(missing_ok=True)
        try:
            shutil.copy2(src, tmp)
            if tmp.stat().st_size != src.stat().st_size:
                raise SystemExit(f"short copy: {src} -> {dest}")
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        return
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src,
        dest,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".cache", "__pycache__"),
        copy_function=copy_file_logged,
    )
    verify_tree(src, dest)


def download_item(item: dict, dest: Path) -> None:
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is missing. Install Tabby extras / pip install huggingface_hub."
        ) from exc

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    repo = item["repo"]
    revision = item.get("revision") or None
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Carriage-return tqdm bars look like noise inside dialog --progressbox.
    # Keep one line per file (note()) and only enable bars on a real tty.
    if sys.stdout.isatty() and os.environ.get("TABBY_NESTED_UI") != "1":
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"
        try:
            from huggingface_hub.utils import enable_progress_bars

            enable_progress_bars()
        except Exception:
            pass
    else:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    try:
        if item.get("kind") == "file":
            tmp = dest.parent / f".hf-{dest.name}"
            tmp.mkdir(parents=True, exist_ok=True)
            try:
                path = hf_hub_download(
                    repo_id=repo,
                    filename=item["remote"],
                    revision=revision,
                    local_dir=str(tmp),
                    token=token,
                )
                shutil.move(path, dest)
            finally:
                # An interrupted download otherwise leaves a multi-GB .hf-* dir
                # that the next run neither sees nor reuses.
                shutil.rmtree(tmp, ignore_errors=True)
            return
        snapshot_download(
            repo_id=repo,
            revision=revision,
            local_dir=str(dest),
            token=token,
        )
    except Exception as exc:
        hint = ""
        text = str(exc)
        if "401" in text or "403" in text or "gated" in text.lower():
            hint = " (gated repo: huggingface-cli login, or set HF_TOKEN)"
        raise SystemExit(f"download failed for {repo}: {exc}{hint}") from exc


def ensure_item(name: str, item: dict, tabby: Path, comfy: Path, cache_root: Path | None) -> str:
    dest = dest_path(item, tabby, comfy)
    if is_ready(dest, item):
        note(f"    have {name} ({dest})")
        return "have"
    cached = find_cache(item, cache_root)
    if cached is not None:
        note(f"    copy {name} from {cached}")
        copy_from_cache(cached, dest, item.get("kind") or "snapshot")
        if is_ready(dest, item):
            return "copy"
        note(f"    copy of {name} was incomplete; downloading")
    note(f"    download {name} from {item['repo']}")
    note(f"      dest {dest}")
    download_item(item, dest)
    if not is_ready(dest, item):
        raise SystemExit(f"{name} finished but marker files are missing in {dest}")
    return "download"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--tabby", type=Path, required=True)
    parser.add_argument("--comfy", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--set", dest="model_set", default="core")
    args = parser.parse_args(argv)

    catalog = load_catalog(args.catalog)
    items = catalog.get("items") or {}
    cache = args.cache if args.cache and args.cache.is_dir() else None
    selected = select_ids(catalog, args.model_set)
    print(f"==> Weights ({args.model_set}): {', '.join(selected)}", flush=True)
    if cache:
        print(f"    cache: {cache}", flush=True)
    else:
        print("    cache: none (Hugging Face)", flush=True)

    for name in selected:
        item = items.get(name)
        if not item:
            raise SystemExit(f"catalog is missing item {name!r}")
        ensure_item(name, item, args.tabby, args.comfy, cache)
    return 0


if __name__ == "__main__":
    sys.exit(main())

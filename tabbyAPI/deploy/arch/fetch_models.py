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


SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pyenv",
    "pyenv",
    "lost+found",
    "$RECYCLE.BIN",
    "System Volume Information",
}
MAX_SEARCH_DEPTH = 6
MAX_WALK_DIRS = 4000


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _wanted_names(item: dict) -> list[str]:
    names: list[str] = []
    dest = item.get("dest") or ""
    if dest:
        names.append(Path(dest).name)
    for rel in item.get("cache") or []:
        names.append(Path(rel).name)
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _relative_suffixes(item: dict) -> list[Path]:
    suffixes: list[Path] = []
    for rel in item.get("cache") or []:
        suffixes.append(Path(rel))
    dest = item.get("dest") or ""
    if dest.startswith("tabby/"):
        rel = Path(dest[len("tabby/") :])
        suffixes.extend((rel, Path(rel.name), Path("tabby-stack") / "tabbyAPI" / rel))
    elif dest.startswith("comfy/"):
        rel = Path(dest[len("comfy/") :])
        suffixes.extend(
            (
                rel,
                Path("ComfyUI") / rel,
                Path("tabby-stack") / "ComfyUI" / rel,
                Path(rel.name),
            )
        )
        if len(rel.parts) >= 2:
            suffixes.append(Path(*rel.parts[-2:]))
    return _unique_paths(suffixes)


def _hub_snapshot_paths(item: dict, cache_root: Path) -> list[Path]:
    repo = item.get("repo") or ""
    if "/" not in repo:
        return []
    hub_name = "models--" + repo.replace("/", "--")
    rev = item.get("revision") or "main"
    remote = item.get("remote") or ""
    remote_name = Path(remote).name if remote else ""
    out: list[Path] = []
    for base in (
        cache_root,
        cache_root / "hub",
        cache_root / "huggingface" / "hub",
        cache_root / ".cache" / "huggingface" / "hub",
    ):
        snap = base / hub_name / "snapshots" / rev
        if item.get("kind") == "file":
            if remote:
                out.append(snap / remote)
            if remote_name:
                out.append(snap / remote_name)
        else:
            out.append(snap)
    return _unique_paths(out)


def _cache_hit(item: dict, candidate: Path) -> bool:
    if item.get("kind") == "file":
        return candidate.is_file() and candidate.stat().st_size > 0
    return candidate.is_dir() and is_ready(candidate, item)


def find_cache(item: dict, cache_root: Path | None) -> Path | None:
    """Return an existing copy of this item under cache_root, if any.

    Exact catalog paths are tried first (a tabby-stack tree). If those miss,
    the given folder is searched for the same file or directory names so a
    models/ dir, a USB mount, or a Hugging Face hub cache still copies.
    """
    if cache_root is None:
        return None
    try:
        cache_root = cache_root.resolve()
    except OSError:
        return None
    if not cache_root.is_dir():
        return None

    tried: set[Path] = set()

    def consider(candidate: Path) -> Path | None:
        try:
            candidate = candidate.resolve()
        except OSError:
            return None
        if candidate in tried:
            return None
        tried.add(candidate)
        if _cache_hit(item, candidate):
            return candidate
        return None

    wanted = set(_wanted_names(item))
    if cache_root.name in wanted:
        hit = consider(cache_root)
        if hit is not None:
            return hit

    for rel in _relative_suffixes(item):
        hit = consider(cache_root / rel)
        if hit is not None:
            return hit

    for candidate in _hub_snapshot_paths(item, cache_root):
        hit = consider(candidate)
        if hit is not None:
            return hit

    if not wanted:
        return None

    walked = 0
    root_depth = len(cache_root.parts)
    for dirpath, dirnames, filenames in os.walk(cache_root, followlinks=False):
        walked += 1
        if walked > MAX_WALK_DIRS:
            break
        here = Path(dirpath)
        depth = len(here.parts) - root_depth
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIR_NAMES and not name.startswith(".")
        ]
        if depth > MAX_SEARCH_DEPTH:
            dirnames.clear()
            continue
        if item.get("kind") == "file":
            for name in filenames:
                if name in wanted:
                    hit = consider(here / name)
                    if hit is not None:
                        return hit
        else:
            if here.name in wanted:
                hit = consider(here)
                if hit is not None:
                    return hit
            for name in list(dirnames):
                if name in wanted:
                    hit = consider(here / name)
                    if hit is not None:
                        return hit
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
    # Carriage-return tqdm bars look like noise inside the installer gauge.
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

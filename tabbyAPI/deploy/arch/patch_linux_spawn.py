#!/usr/bin/env python3
"""Make TabbyAPI subprocess spawns work on Linux and Windows.

Python rejects creationflags=... on Linux. Chat 'switch to …' used to 500
because phrase_switch.py always passed Windows CREATE_NO_WINDOW.
"""

from __future__ import annotations

import sys
from pathlib import Path

PHRASE_OLD = """def start_switch(name: str) -> None:
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    LOG.touch(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\\n--- switch {name} (from Cursor chat) ---\\n")
        log.flush()
        subprocess.Popen(
            [str(PYTHON), str(SWITCHER), name],
            stdout=log,
            stderr=log,
            cwd=str(ROOT),
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        )
    xlogger.info(f"Phrase switch started: {name}")
"""

PHRASE_NEW = """def start_switch(name: str) -> None:
    LOG.touch(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\\n--- switch {name} (from Cursor chat) ---\\n")
        log.flush()
        kwargs: dict = {
            "cwd": str(ROOT),
            "stdout": log,
            "stderr": log,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([str(PYTHON), str(SWITCHER), name], **kwargs)
    xlogger.info(f"Phrase switch started: {name}")
"""

GPU_OLD = """    COMFY_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = COMFY_LOG.open("a", encoding="utf-8")
    creation = 0
    if os.name == "nt":
        creation = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    print(f"  Starting ComfyUI ({COMFY_DIR})...")
    subprocess.Popen(
        [
            str(COMFY_PYTHON),
            "main.py",
            "--listen",
            "127.0.0.1",
            "--port",
            "8188",
        ],
        cwd=str(COMFY_DIR),
        stdout=log,
        stderr=log,
        creationflags=creation,
    )
"""

GPU_NEW = """    COMFY_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = COMFY_LOG.open("a", encoding="utf-8")
    kwargs: dict = {
        "cwd": str(COMFY_DIR),
        "stdout": log,
        "stderr": log,
    }
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    print(f"  Starting ComfyUI ({COMFY_DIR})...")
    subprocess.Popen(
        [
            str(COMFY_PYTHON),
            "main.py",
            "--listen",
            "127.0.0.1",
            "--port",
            "8188",
        ],
        **kwargs,
    )
"""


def replace_once(path: Path, old: str, new: str, already_ok: str) -> str:
    text = path.read_text(encoding="utf-8")
    if already_ok in text and old not in text:
        return f"  {path.name} already Linux-safe"
    if old not in text:
        raise SystemExit(
            f"{path} still needs a Linux spawn patch, but the expected block was not found."
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"  patched {path}"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/tabbyAPI", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    phrase = root / "common" / "phrase_switch.py"
    gpu = root / "common" / "gpu_mode.py"
    if not phrase.is_file() or not gpu.is_file():
        print(f"Missing common/*.py under {root}", file=sys.stderr)
        return 1
    print(replace_once(phrase, PHRASE_OLD, PHRASE_NEW, 'kwargs["start_new_session"] = True'))
    print(replace_once(gpu, GPU_OLD, GPU_NEW, 'kwargs["start_new_session"] = True'))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

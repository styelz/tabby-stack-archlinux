"""Bounce TabbyAPI (and Comfy if needed) after a chat ``restart``.

Spawned detached so the chat reply can flush before this process is killed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def restart_units(mode: str = "llm") -> int:
    """Stop or restart user units. mode is llm or comfy."""
    if mode == "comfy":
        subprocess.run(["systemctl", "--user", "reset-failed", "comfyui"], check=False)
        subprocess.run(["systemctl", "--user", "restart", "comfyui"], check=False)
    else:
        subprocess.run(["systemctl", "--user", "stop", "comfyui"], check=False)
    subprocess.run(["systemctl", "--user", "reset-failed", "tabbyapi"], check=False)
    return subprocess.run(["systemctl", "--user", "restart", "tabbyapi"]).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restart the TabbyAPI stack")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--mode", default="llm", choices=("llm", "comfy"))
    parser.add_argument("--lock", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.delay > 0:
        time.sleep(args.delay)
    if args.lock is not None:
        args.lock.unlink(missing_ok=True)
    return restart_units(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())

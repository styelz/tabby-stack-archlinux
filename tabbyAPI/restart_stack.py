"""Bounce TabbyAPI (and Comfy if needed) after a chat ``restart``.

Spawned detached so the chat reply can flush before this process is killed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

JOBS_PERSIST = Path(__file__).resolve().parent / "pasted-images" / "mcp_jobs.json"
RESTART_ABANDON_REASON = "TabbyAPI restarted before this job finished."


def abandon_persisted_jobs(
    path: Path | None = None,
    reason: str = RESTART_ABANDON_REASON,
) -> int:
    """Rewrite mcp_jobs.json so queued/running jobs cannot block the next process."""
    persist = path or JOBS_PERSIST
    try:
        raw = json.loads(persist.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(raw, list):
        return 0
    changed = 0
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") not in ("queued", "running"):
            continue
        entry["status"] = "error"
        entry["phase"] = "error"
        entry["client_saved"] = False
        if not entry.get("error"):
            entry["error"] = reason
        for item in entry.get("items") or []:
            if isinstance(item, dict) and item.get("status") in ("queued", "running"):
                item["status"] = "error"
                if not item.get("error"):
                    item["error"] = reason
        changed += 1
    if not changed:
        return 0
    try:
        tmp = persist.with_name(persist.name + ".tmp")
        tmp.write_text(json.dumps(raw), encoding="utf-8")
        tmp.replace(persist)
    except OSError:
        return 0
    return changed


def restart_units(mode: str = "llm") -> int:
    """Stop or restart user units. mode is llm or comfy."""
    from common.gpu_mode import user_systemd_env

    env = user_systemd_env()
    if mode == "comfy":
        subprocess.run(
            ["systemctl", "--user", "reset-failed", "comfyui"],
            check=False,
            env=env,
        )
        subprocess.run(
            ["systemctl", "--user", "restart", "comfyui"],
            check=False,
            env=env,
        )
    else:
        subprocess.run(["systemctl", "--user", "stop", "comfyui"], check=False, env=env)
    subprocess.run(["systemctl", "--user", "reset-failed", "tabbyapi"], check=False, env=env)
    return subprocess.run(["systemctl", "--user", "restart", "tabbyapi"], env=env).returncode


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
    abandon_persisted_jobs()
    return restart_units(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())

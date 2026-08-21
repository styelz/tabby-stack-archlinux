"""Restart TabbyAPI if the process dies (OOM crash, CUDA abort, etc.)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "main.py"
DELAY_SEC = 5
FAST_CRASH_SEC = 90
FAST_CRASH_LIMIT = 3


def main() -> int:
    python = sys.executable
    fast_exits: list[float] = []

    try:
        from common.gpu_mode import start_comfy_journal_forwarder

        start_comfy_journal_forwarder()
    except Exception as exc:
        print(f"Comfy journal forwarder not started: {exc}", flush=True)

    # The tunnel is started by main.py's entrypoint, which runs on every
    # supervised start as well as on a direct ./start.sh. Starting it here too
    # raced with that call and left a second supervisor retrying forever.
    print("TabbyAPI watchdog: Ctrl+C stops restarts.", flush=True)
    while True:
        started = time.time()
        print(f"\n--- starting TabbyAPI ({python}) ---\n", flush=True)
        try:
            result = subprocess.run([python, str(MAIN)], cwd=str(ROOT))
        except KeyboardInterrupt:
            print("\nWatchdog stopped.", flush=True)
            return 0

        code = result.returncode
        lived = time.time() - started
        if code == 0:
            print("TabbyAPI exited cleanly.", flush=True)
            return 0

        print(f"\nTabbyAPI exited with code {code} after {lived:.0f}s.", flush=True)
        now = time.time()
        fast_exits = [t for t in fast_exits if now - t < FAST_CRASH_SEC]
        if lived < FAST_CRASH_SEC:
            fast_exits.append(now)
        if len(fast_exits) >= FAST_CRASH_LIMIT:
            print(
                f"Crashed {FAST_CRASH_LIMIT} times in {FAST_CRASH_SEC}s "
                "(likely OOM on load). Not restarting. Lower context and start again.",
                flush=True,
            )
            return code or 1

        print(f"Restarting in {DELAY_SEC}s...", flush=True)
        try:
            time.sleep(DELAY_SEC)
        except KeyboardInterrupt:
            print("\nWatchdog stopped.", flush=True)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())

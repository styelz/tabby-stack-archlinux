"""Optional reverse SSH tunnel when TabbyAPI starts.

Disabled unless TABBY_SSH_REMOTE is set (for example user@host).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FORWARD = "127.0.0.1:12345:127.0.0.1:5000"
LOG_PATH = ROOT / "ssh-forwarder.log"


def ssh_remote() -> str:
    return (os.environ.get("TABBY_SSH_REMOTE") or "").strip()


def ssh_forward() -> str:
    return (os.environ.get("TABBY_SSH_FORWARD") or DEFAULT_FORWARD).strip()


def key_path() -> Path:
    env_key = (os.environ.get("TABBY_SSH_KEY") or "").strip()
    if env_key:
        return Path(env_key)
    return Path.home() / ".ssh" / "id_ed25519"


def ssh_command(key: Path | None = None, remote: str | None = None) -> list[str]:
    key = key or key_path()
    host = remote if remote is not None else ssh_remote()
    if not host:
        raise ValueError("TABBY_SSH_REMOTE is not set")
    return [
        "ssh",
        "-i",
        str(key),
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "TCPKeepAlive=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-N",
        "-R",
        ssh_forward(),
        host,
    ]


def tunnel_running() -> bool:
    forward = ssh_forward()
    remote = ssh_remote()
    try:
        import psutil
    except ImportError:
        return _tunnel_running_fallback(forward, remote)
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = proc.info.get("cmdline") or []
        except (psutil.Error, TypeError):
            continue
        joined = " ".join(str(part) for part in cmd)
        if not joined:
            continue
        # The supervisor runs as "python .../ssh_forwarder.py", so filtering on
        # the process name being ssh would never match it and we would keep
        # spawning duplicates. The tunnel itself carries the -R forward spec.
        if "ssh_forwarder.py" in joined:
            return True
        if forward in joined:
            return True
        if remote and remote in joined:
            return True
    return False


def _tunnel_running_fallback(forward: str, remote: str) -> bool:
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["wmic", "process", "where", "name='ssh.exe'", "get", "CommandLine"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        return _matches(out, forward, remote)
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "args="], text=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return _matches(out, forward, remote)


def _matches(out: str, forward: str, remote: str) -> bool:
    if "ssh_forwarder.py" in out or forward in out:
        return True
    return bool(remote) and remote in out


def run_loop() -> None:
    if not ssh_remote():
        print("SSH reverse tunnel skipped: TABBY_SSH_REMOTE is not set", flush=True)
        return
    key = key_path()
    if not key.is_file():
        print(f"SSH key missing: {key}", flush=True)
        return
    cmd = ssh_command(key)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    while True:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{stamp}] Starting SSH reverse tunnel...", flush=True)
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(f"[{stamp}] {' '.join(cmd)}\n")
            result = subprocess.run(cmd, stdout=log, stderr=log)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[{stamp}] SSH exited with code {result.returncode}. Reconnecting in 5 seconds...",
            flush=True,
        )
        time.sleep(5)


def ensure_ssh_forwarder() -> bool:
    """Start the reverse tunnel if configured and not already running. Never blocks the API."""
    remote = ssh_remote()
    if not remote:
        print("SSH reverse tunnel skipped: TABBY_SSH_REMOTE is not set")
        return False
    if tunnel_running():
        print("SSH reverse tunnel already running")
        return True
    key = key_path()
    if not key.is_file():
        print(f"SSH reverse tunnel skipped: key not found at {key}")
        return False
    kwargs: dict = {
        "cwd": str(ROOT),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, str(Path(__file__).resolve())], **kwargs)
    print(f"SSH reverse tunnel starting ({remote} {ssh_forward()})")
    return True


if __name__ == "__main__":
    run_loop()

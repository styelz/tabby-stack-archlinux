"""Helpers for the /v1/ui management console."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from loguru import logger

from common.logger import is_ui_access_line

ROOT = Path(__file__).resolve().parent.parent
STACK_ROOT = ROOT.parent
JOURNAL_UNITS = ("tabbyapi", "comfyui")
CONSOLE_SYSTEM = (
    "You are chatting in the Tabby Stack web console. Answer in this conversation "
    "only. Do not write project files, HTML, CSS, or scripts to disk. "
    "If the user asks for an image, describe or generate it; the UI will show PNGs."
)
PROCESS_LOGS: deque[str] = deque(maxlen=4000)
_SINK_ID: Optional[int] = None
_STARTED_AT = time.time()


def visible_log_lines(lines, limit: Optional[int] = None) -> list[str]:
    out = [line for line in lines if line and not is_ui_access_line(line)]
    if limit is None:
        return out
    return out[-max(1, int(limit)) :]


def install_log_sink() -> None:
    global _SINK_ID
    if _SINK_ID is not None:
        return

    def _sink(message):
        text = str(message).rstrip("\n")
        if not text or is_ui_access_line(text):
            return
        PROCESS_LOGS.append(text)

    _SINK_ID = logger.add(
        _sink,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        colorize=False,
        enqueue=False,
    )


def journalctl_cmd(*, follow: bool = False, lines: int = 300) -> list[str]:
    cmd = [
        "journalctl",
        "--user",
        "--no-pager",
        "-o",
        "short-iso",
    ]
    for unit in JOURNAL_UNITS:
        cmd.extend(["-u", unit])
    if follow:
        # `-n 0 -f` can sit open without emitting new lines on some systemd
        # versions. `--since now` follows from this moment; the UI catches up
        # any gap from /logs/history.
        cmd.extend(["--since", "now", "-f"])
        return cmd
    count = max(1, min(int(lines), 5000))
    cmd.extend(["-n", str(count)])
    return cmd


def journalctl_history(lines: int = 300) -> list[str]:
    wanted = max(1, min(int(lines), 5000))
    fetch = min(5000, max(wanted * 6, 800))
    if shutil.which("journalctl") is None:
        return visible_log_lines(PROCESS_LOGS, wanted)
    try:
        completed = subprocess.run(
            journalctl_cmd(follow=False, lines=fetch),
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return visible_log_lines(PROCESS_LOGS, wanted)
    text = completed.stdout or ""
    if completed.returncode != 0 and not text.strip():
        return visible_log_lines(PROCESS_LOGS, wanted)
    return visible_log_lines(text.splitlines(), wanted)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except (asyncio.TimeoutError, ProcessLookupError):
        process.kill()


async def stream_journal_lines() -> AsyncIterator[str]:
    if shutil.which("journalctl") is None:
        async for line in _stream_process_logs():
            yield line
        return
    while True:
        process = await asyncio.create_subprocess_exec(
            *journalctl_cmd(follow=True),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            assert process.stdout is not None
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line and not is_ui_access_line(line):
                    yield line
        except asyncio.CancelledError:
            await _stop_process(process)
            raise
        await _stop_process(process)
        await asyncio.sleep(0.4)


async def _stream_process_logs() -> AsyncIterator[str]:
    index = 0
    for line in list(PROCESS_LOGS):
        index += 1
        if line and not is_ui_access_line(line):
            yield line
    while True:
        await asyncio.sleep(0.25)
        current = list(PROCESS_LOGS)
        if len(current) < index:
            index = 0
        while index < len(current):
            line = current[index]
            index += 1
            if line and not is_ui_access_line(line):
                yield line


def nvidia_stats() -> dict[str, Any]:
    if shutil.which("nvidia-smi") is None:
        return {}
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {}
    rows = (out or "").strip().splitlines()
    if not rows:
        return {}
    parts = [part.strip() for part in rows[0].split(",")]
    if len(parts) < 5:
        return {"name": rows[0]}
    try:
        used = int(float(parts[1]))
        total = int(float(parts[2]))
        util = int(float(parts[3]))
        temp = int(float(parts[4]))
    except ValueError:
        return {"name": parts[0]}
    return {
        "name": parts[0],
        "memory_used_mib": used,
        "memory_total_mib": total,
        "utilization_pct": util,
        "temperature_c": temp,
    }


def unit_active(name: str) -> Optional[bool]:
    if shutil.which("systemctl") is None:
        return None
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "is-active", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() == "active"


def _model_card() -> dict[str, Any]:
    from common import model

    container = getattr(model, "container", None)
    if not container or not getattr(container, "loaded", False):
        return {}
    try:
        card = container.model_info()
        payload = card.model_dump() if hasattr(card, "model_dump") else dict(card)
    except Exception:
        payload = {"id": getattr(getattr(container, "model_dir", None), "name", None)}
    params = payload.get("parameters") or {}
    return {
        "id": payload.get("id"),
        "max_seq_len": params.get("max_seq_len"),
        "cache_size": params.get("cache_size"),
        "cache_mode": params.get("cache_mode"),
        "use_vision": params.get("use_vision"),
    }


async def stack_status(request=None, username: str = "") -> dict[str, Any]:
    from common.gpu_mode import comfy_up, public_api_base, read_mode
    from common.health import HealthManager
    from common.phrase_switch import last_llm_profile_name, switch_lock_held, switch_lock_name
    from images.jobs import active_mcp_image_job, loaded_tabby_name
    from select_model import available_profiles, last_profile
    from ui.occupancy import snapshot as stack_queue_snapshot

    mode = read_mode()
    tabby = loaded_tabby_name()
    gpu_mode = "llm" if tabby else (mode.get("mode") or "llm")
    try:
        healthy, issues = await HealthManager.is_service_healthy()
        issue_text = [
            issue.description if hasattr(issue, "description") else str(issue) for issue in issues
        ]
    except Exception:
        healthy, issue_text = True, []
    lock_name = switch_lock_name()
    lock_held = switch_lock_held()
    restarting = lock_held and lock_name == "restart"
    switching = lock_held and not restarting
    job = active_mcp_image_job()
    job_info = None
    if job:
        job_info = {
            "id": getattr(job, "id", None),
            "status": getattr(job, "status", None),
            "phase": getattr(job, "phase", None),
            "count": getattr(job, "count", None),
            "current_index": getattr(job, "current_index", 0),
            "done_count": getattr(job, "done_count", 0),
            "wait_s": getattr(job, "wait_s", None),
            "wait_text": getattr(job, "wait_text", None),
            "prompt": getattr(job, "prompt", None),
            "started_at": getattr(job, "started_at", None),
        }
    http_up = comfy_up()
    comfy_unit = unit_active("comfyui")
    job_phase = (job_info or {}).get("phase")
    comfy_booting = (not http_up) and (bool(comfy_unit) or job_phase == "starting_comfy")
    if comfy_booting and not restarting:
        switching = True
    return {
        "ok": True,
        "gpu_mode": gpu_mode,
        "comfy_up": http_up,
        "tabby_model": tabby,
        "profile": last_llm_profile_name() or last_profile(),
        "profiles": available_profiles(),
        "model": _model_card(),
        "health": {"healthy": healthy, "issues": issue_text},
        "units": {
            "tabbyapi": unit_active("tabbyapi"),
            "comfyui": comfy_unit,
        },
        "gpu": nvidia_stats(),
        "host": _host_live(),
        "uptime_s": int(time.time() - _STARTED_AT),
        "api_base": public_api_base(request),
        "job": job_info,
        "switching": switching,
        "restarting": restarting,
        "busy": lock_held or comfy_booting,
        "switch_target": lock_name or ("comfy" if comfy_booting else None),
        "user": os.environ.get("USER") or "",
        "now": datetime.now(timezone.utc).isoformat(),
        "stack_queue": stack_queue_snapshot(username),
    }


def _host_live() -> dict[str, Any]:
    """One-shot CPU / RAM / load for the status cards (not the chart history)."""
    cpu = None
    ram = None
    load1 = None
    try:
        import psutil

        cpu = float(psutil.cpu_percent(interval=None))
        ram = float(psutil.virtual_memory().percent)
    except Exception:
        pass
    try:
        load1 = float(os.getloadavg()[0])
    except (OSError, AttributeError):
        pass
    return {
        "cpu_pct": None if cpu is None else round(cpu, 1),
        "ram_pct": None if ram is None else round(ram, 1),
        "load1": None if load1 is None else round(load1, 2),
    }


def gallery_listing(
    page: int = 1,
    per_page: int = 24,
    *,
    username: str = "",
    is_admin: bool = False,
) -> dict[str, Any]:
    from common.gallery_owners import filter_files, owner_of
    from common.gpu_mode import gallery_page, gallery_thumb_href, list_generated_files

    files = filter_files(list_generated_files(), username, is_admin)
    shown, page, pages, per_page = gallery_page(files, page, per_page)
    items = []
    for path in shown:
        try:
            stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            when = stamp.strftime("%Y-%m-%d %H:%M UTC")
            size = path.stat().st_size
        except OSError:
            when = ""
            size = 0
        items.append(
            {
                "name": path.name,
                "mtime": when,
                "size": size,
                "url": f"/v1/ui/gallery/file/{path.name}",
                "thumb": f"/v1/ui/gallery/thumb/{path.name}",
                "public_thumb": gallery_thumb_href(path.name),
                "owner": owner_of(path.name) or "",
            }
        )
    return {
        "items": items,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": len(files),
    }


UPDATE_PROMPT_NAME = "tabby-update-prompt.json"
GIT_UPDATE_TIMEOUT_S = 300


def start_stack_restart() -> dict[str, Any]:
    from common.phrase_switch import restart_reply_text, start_restart

    ok = start_restart()
    return {
        "ok": ok,
        "message": restart_reply_text() if ok else "Could not start a restart (systemctl missing?).",
    }


def _update_log_tail(limit: int = 40) -> str:
    path = STACK_ROOT / "tabby-update.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max(1, limit) :])


def load_update_prompt(path: Path | None = None) -> dict[str, Any] | None:
    target = path if path is not None else STACK_ROOT / UPDATE_PROMPT_NAME
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _prompt_response(prompt: dict[str, Any] | None, fallback: str) -> dict[str, Any]:
    if not prompt:
        return {"ok": True, "message": fallback, "ask_restart": False}
    summary = str(prompt.get("summary") or fallback)
    text = str(prompt.get("text") or "").strip()
    return {
        "ok": True,
        "message": summary,
        "ask_restart": bool(text),
        "restart_title": str(prompt.get("title") or "Restart API?"),
        "restart_text": text,
        "restart_yes": str(prompt.get("yes_label") or "Restart"),
        "restart_no": str(prompt.get("no_label") or "Skip"),
        "pulled": bool(prompt.get("pulled")),
    }


def start_stack_update(*, full: bool = False) -> dict[str, Any]:
    script = STACK_ROOT / "update.sh"
    if not script.is_file():
        return {"ok": False, "message": f"update.sh not found at {script}"}
    if full:
        args = ["bash", str(script), "--all", "--restart"]
        try:
            subprocess.Popen(
                args,
                cwd=str(STACK_ROOT),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return {"ok": False, "message": str(exc)}
        return {
            "ok": True,
            "message": (
                "Started full (git + deps) update. TabbyAPI will bounce when it finishes. "
                "Watch Logs for progress."
            ),
        }

    prompt_path = STACK_ROOT / UPDATE_PROMPT_NAME
    try:
        prompt_path.unlink(missing_ok=True)
    except OSError:
        pass
    env = os.environ.copy()
    env["TABBY_UPDATE_RESTART"] = "0"
    try:
        proc = subprocess.run(
            ["bash", str(script), "--git", "--no-restart"],
            cwd=str(STACK_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=GIT_UPDATE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Git update timed out after 5 minutes."}
    except OSError as exc:
        return {"ok": False, "message": str(exc)}
    if proc.returncode != 0:
        detail = _update_log_tail() or (proc.stderr or proc.stdout or "").strip()
        return {
            "ok": False,
            "message": detail[:1500] if detail else "update.sh --git failed.",
        }
    return _prompt_response(load_update_prompt(prompt_path), "Git update finished.")


def sanitize_chat_payload(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages is required")
    clean_messages = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "user")
        if role not in ("system", "user", "assistant"):
            continue
        content = raw.get("content")
        if isinstance(content, list):
            texts = []
            images = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image = part.get("image_url")
                    url = ""
                    if isinstance(image, dict):
                        url = str(image.get("url") or "")
                    elif isinstance(image, str):
                        url = image
                    if url.startswith("data:image") and 32 < len(url) < 12_000_000:
                        images.append({"type": "image_url", "image_url": {"url": url}})
                elif isinstance(part, dict) and part.get("type") == "text":
                    texts.append(str(part.get("text") or ""))
                elif isinstance(part, str):
                    texts.append(part)
            text = "\n".join(texts)
            if images:
                parts: list[dict[str, Any]] = []
                if text:
                    parts.append({"type": "text", "text": text})
                parts.extend(images)
                content = parts
            else:
                content = text
        if content is None:
            content = ""
        if not isinstance(content, list):
            content = str(content)
        clean_messages.append({"role": role, "content": content})
    if not any(item["role"] == "system" for item in clean_messages):
        clean_messages.insert(0, {"role": "system", "content": CONSOLE_SYSTEM})
    payload = {
        "messages": clean_messages,
        "stream": bool(body.get("stream", True)),
    }
    if body.get("temperature") is not None:
        payload["temperature"] = body["temperature"]
    if body.get("max_tokens") is not None:
        payload["max_tokens"] = body["max_tokens"]
    return payload


def sanitize_code_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Chat sanitizer, but force the Code-mode system prompt and keep chat_id."""
    from ui.code_agent import CODE_SYSTEM
    from ui.workspace import safe_name

    payload = sanitize_chat_payload(body)
    messages = [item for item in payload["messages"] if item.get("role") != "system"]
    messages.insert(0, {"role": "system", "content": CODE_SYSTEM})
    payload["messages"] = messages
    raw_id = str(body.get("chat_id") or "").strip()
    if not raw_id:
        raise ValueError("chat_id is required in Code mode")
    payload["chat_id"] = safe_name(raw_id)
    payload["mode"] = "code"
    return payload

#!/usr/bin/env python3
"""Stdio MCP for Cursor: queue TabbyAPI images and write PNGs locally.

Remote HTTP MCP at {API}/v1/mcp cannot touch the coding disk. This process
runs on the IDE machine, forwards generate_image to that API, then a detached
saver polls GET /images/jobs/{id} and writes each PNG to output_path even if
the agent chat ends.

Env:
  TABBY_API_BASE  OpenAI-shaped base, e.g. https://host/v1
  TABBY_API_KEY   optional Bearer token (skip if auth is disabled)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

TOOL_NAME = "generate_image"
GET_JOB_NAME = "get_image_job"
PROTOCOL_VERSION = "2025-03-26"
JOB_ID_MARK = "Job "


def _api_base() -> str:
    return (os.environ.get("TABBY_API_BASE") or "").strip().rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = (os.environ.get("TABBY_API_KEY") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:/")
_MACHINE_PARENTS = frozenset(
    {
        "home",
        "users",
        "user",
        "tmp",
        "var",
        "private",
        "mnt",
        "media",
        "root",
        "opt",
        "usr",
        "etc",
        "windows",
        "program files",
        "programdata",
        "appdata",
        "volumes",
        "cursor",
        "vscode",
        "documents",
        "desktop",
        "downloads",
        "onedrive",
    }
)
_PROJECT_PARENTS = frozenset(
    {
        "projects",
        "project",
        "repos",
        "repo",
        "src",
        "workspace",
        "work",
        "code",
        "dev",
    }
)
_WORKSPACE_PARENTS = _MACHINE_PARENTS | _PROJECT_PARENTS


def _looks_absolute(text: str, path: Path) -> bool:
    return bool(
        path.is_absolute() or _DRIVE_ABS_RE.match(text) or text.startswith("//")
    )


def _cwd_relative_png(text: str) -> Optional[str]:
    """If the path is under this process cwd (the coding project), keep that relpath."""
    try:
        candidate = Path(text)
        if not candidate.is_absolute():
            return None
        rel = candidate.resolve().relative_to(Path.cwd().resolve())
    except (OSError, ValueError, RuntimeError):
        return None
    if any(part == ".." for part in rel.parts):
        return None
    return rel.as_posix()


def _project_png_from_abs(raw: str) -> Optional[str]:
    text = str(raw or "").strip().replace("\\", "/")
    parts = [
        part
        for part in Path(text).parts
        if part not in ("/", "\\") and not (len(part) == 2 and part[1] == ":")
    ]
    if not parts or any(part == ".." for part in parts) or "images" not in parts:
        return None
    idx = len(parts) - 1 - parts[::-1].index("images")
    start = idx
    if idx > 0:
        parent = parts[idx - 1]
        keep = (
            parent.lower() not in _WORKSPACE_PARENTS
            and not parent.startswith(".")
            and not (idx >= 2 and parts[idx - 2].lower() in _MACHINE_PARENTS)
        )
        if keep:
            start = idx - 1
    rel = Path(*parts[start:])
    if rel.suffix.lower() != ".png":
        rel = rel.with_suffix(".png")
    cleaned = [part for part in rel.parts if part not in ("", ".")]
    if not cleaned:
        return None
    return Path(*cleaned).as_posix()


def safe_rel_png_path(raw: str, default: str = "images/generated.png") -> str:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        text = default
    path = Path(text)
    if any(part == ".." for part in path.parts):
        path = Path(default)
    elif _looks_absolute(text, path):
        recovered = _cwd_relative_png(text) or _project_png_from_abs(text)
        path = Path(recovered) if recovered else Path(default)
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    parts = [part for part in path.parts if part not in ("", ".")]
    if not parts:
        parts = list(Path(default).parts)
    return Path(*parts).as_posix()


def rewrite_generate_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Make output_path project-relative before the GPU API stores the job."""
    args = dict(arguments or {})
    if args.get("output_path"):
        args["output_path"] = safe_rel_png_path(str(args.get("output_path") or ""))
    images = args.get("images")
    if isinstance(images, list):
        rewritten: list[Any] = []
        for item in images:
            if isinstance(item, dict):
                row = dict(item)
                if row.get("output_path"):
                    row["output_path"] = safe_rel_png_path(str(row.get("output_path") or ""))
                rewritten.append(row)
            else:
                rewritten.append(item)
        args["images"] = rewritten
    return args


def _read_message() -> Optional[dict[str, Any]]:
    header_line = sys.stdin.buffer.readline()
    if not header_line:
        return None
    if header_line.lstrip().startswith(b"{"):
        return json.loads(header_line.decode("utf-8"))
    headers: dict[str, str] = {}
    line = header_line
    while line not in (b"\r\n", b"\n", b""):
        raw = line.decode("utf-8", errors="replace")
        if ":" in raw:
            key, value = raw.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        line = sys.stdin.buffer.readline()
        if not line:
            break
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    payload = sys.stdin.buffer.read(length)
    return json.loads(payload.decode("utf-8"))


def _write_message(message: dict[str, Any]) -> None:
    blob = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(blob)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(blob)
    sys.stdout.buffer.flush()


def _rpc_result(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _tool_text(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _tools() -> dict[str, Any]:
    output_path = {
        "type": "string",
        "description": (
            "Project-relative PNG path written by the background saver, "
            "e.g. pbptours/images/logo.png. Never /home/... or C:\\..."
        ),
    }
    return {
        "tools": [
            {
                "name": TOOL_NAME,
                "description": (
                    "Queue PNG(s) on TabbyAPI/Comfy and write them to output_path "
                    "automatically (background saver). Returns a job_id immediately. "
                    "Pass every asset in the images array. Prefix qwen-image: for text. "
                    "Do not tell the user to download. Do not use the browser."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "images": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "prompt": {"type": "string"},
                                    "output_path": output_path,
                                    "size": {"type": "string"},
                                    "n": {"type": "integer"},
                                    "qwen_image": {"type": "boolean"},
                                },
                                "required": ["prompt"],
                            },
                        },
                        "output_path": output_path,
                        "size": {"type": "string", "default": "1024x1024"},
                        "n": {"type": "integer", "default": 1},
                        "qwen_image": {"type": "boolean", "default": False},
                    },
                    "required": [],
                },
            },
            {
                "name": GET_JOB_NAME,
                "description": (
                    "Poll the TabbyAPI image job and report which local PNGs already exist. "
                    "The background saver writes files; you do not download."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "wait_s": {"type": "integer", "default": 20},
                    },
                },
            },
        ]
    }


def _http_json(url: str, payload: Optional[dict[str, Any]] = None, timeout: float = 60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    method = "GET" if data is None else "POST"
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _mcp_tool(name: str, arguments: dict[str, Any], timeout: float = 45) -> dict[str, Any]:
    base = _api_base()
    if not base:
        raise RuntimeError("Set TABBY_API_BASE to the IDE /v1 URL")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    reply = _http_json(f"{base}/mcp", body, timeout=timeout)
    result = reply.get("result") if isinstance(reply, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError(f"MCP {name} returned no result")
    return result


def _tool_result_text(result: dict[str, Any]) -> str:
    chunks = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("text"):
            chunks.append(str(item["text"]))
    return "\n".join(chunks)


def parse_job_id(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(JOB_ID_MARK):
            token = stripped[len(JOB_ID_MARK) :].split(":", 1)[0].strip()
            if token:
                return token
        if stripped.startswith("job_id="):
            return stripped.split("=", 1)[1].strip().split()[0]
    return ""


def fetch_job(job_id: str = "") -> Optional[dict[str, Any]]:
    base = _api_base()
    if not base:
        return None
    suffix = f"/images/jobs/{job_id}" if job_id else "/images/jobs"
    try:
        return _http_json(f"{base}{suffix}", timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def download_url(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def _uniquify_paths(paths: list[str]) -> list[str]:
    used: set[str] = set()
    out: list[str] = []
    for raw in paths:
        path = safe_rel_png_path(raw)
        if path not in used:
            used.add(path)
            out.append(path)
            continue
        stem = Path(path)
        index = 2
        while True:
            candidate = stem.with_name(f"{stem.stem}-{index}{stem.suffix}").as_posix()
            if candidate not in used:
                used.add(candidate)
                out.append(candidate)
                break
            index += 1
    return out


def pairs_from_job(job: dict[str, Any]) -> list[tuple[str, str]]:
    planned: list[tuple[str, str]] = []
    items = job.get("items") if isinstance(job.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        dest = safe_rel_png_path(str(item.get("output_path") or ""))
        urls = [url for url in (item.get("urls") or []) if url]
        for url in urls:
            planned.append((str(url), dest))
    dests = _uniquify_paths([path for _, path in planned])
    return [(url, dest) for (url, _), dest in zip(planned, dests)]


def save_available(job: dict[str, Any], saved: set[str]) -> list[str]:
    wrote: list[str] = []
    for url, rel in pairs_from_job(job):
        if rel in saved:
            continue
        path = Path(rel)
        download_url(url, path)
        saved.add(rel)
        wrote.append(rel)
    return wrote


def save_job_until_done(job_id: str, timeout: float = 3600) -> dict[str, Any]:
    deadline = time.time() + timeout
    saved: set[str] = set()
    last: dict[str, Any] = {}
    while time.time() < deadline:
        job = fetch_job(job_id) or {}
        last = job
        if job:
            save_available(job, saved)
            if job.get("status") in ("done", "error"):
                return job
        time.sleep(3)
    return last


def spawn_saver(job_id: str) -> None:
    if not job_id:
        return
    cmd = [sys.executable, str(Path(__file__).resolve()), "--save-job", job_id]
    log_file = Path(tempfile.gettempdir()) / f"tabby-image-saver-{job_id[:8]}.log"
    log_handle = open(log_file, "ab")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "cwd": os.getcwd(),
        "env": os.environ.copy(),
    }
    if os.name == "nt":
        # DETACHED_PROCESS (0x8) often prevents python.exe from starting.
        kwargs["close_fds"] = False
        kwargs["creationflags"] = 0x00000200 | 0x08000000  # NEW_GROUP | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
        kwargs["close_fds"] = True
    subprocess.Popen(cmd, **kwargs)


def _call_generate(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _mcp_tool(TOOL_NAME, rewrite_generate_arguments(arguments), timeout=45)
    except Exception as exc:
        return _tool_text(str(exc), is_error=True)
    text = _tool_result_text(result)
    job_id = parse_job_id(text)
    if job_id:
        spawn_saver(job_id)
        text += (
            "\nA background saver on this machine is writing each PNG to output_path. "
            "Keep the HTML pointing at those paths. Do not download. Do not tell the user to download."
        )
    if result.get("isError"):
        return _tool_text(text or "generate_image failed", is_error=True)
    return _tool_text(text or "queued")


def _call_get_job(arguments: dict[str, Any]) -> dict[str, Any]:
    job_id = str(arguments.get("job_id") or "").strip()
    try:
        result = _mcp_tool(GET_JOB_NAME, arguments, timeout=45)
        text = _tool_result_text(result)
    except Exception as exc:
        text = str(exc)
        result = {"isError": True}
    job = fetch_job(job_id)
    if job:
        if not job_id:
            job_id = str(job.get("id") or "")
        existing = []
        for _url, rel in pairs_from_job(job):
            if Path(rel).is_file():
                existing.append(rel)
        if existing:
            text += "\nAlready on disk:\n" + "\n".join(f"  {path}" for path in existing)
        else:
            text += "\nNo local PNGs yet; the background saver is still writing."
    if result.get("isError"):
        return _tool_text(text, is_error=True)
    return _tool_text(text)


def _handle(message: dict[str, Any]) -> Optional[dict[str, Any]]:
    rpc_id = message.get("id")
    method = message.get("method")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method in (None, "notifications/initialized") or str(method).startswith(
        "notifications/"
    ):
        return None
    if method == "initialize":
        return _rpc_result(
            rpc_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tabby-images", "version": "1.1.0"},
                "instructions": (
                    "Call generate_image once with an images array. PNGs are written "
                    "to output_path automatically. Prefix qwen-image: for text. "
                    "Never tell the user to download. Never use the browser."
                ),
            },
        )
    if method == "ping":
        return _rpc_result(rpc_id, {})
    if method == "tools/list":
        return _rpc_result(rpc_id, _tools())
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name == GET_JOB_NAME:
            return _rpc_result(rpc_id, _call_get_job(arguments))
        if name != TOOL_NAME:
            return _rpc_result(rpc_id, _tool_text(f"Unknown tool {name!r}", is_error=True))
        return _rpc_result(rpc_id, _call_generate(arguments))
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    if "--save-job" in sys.argv:
        try:
            job_id = sys.argv[sys.argv.index("--save-job") + 1]
        except (ValueError, IndexError):
            return 2
        save_job_until_done(job_id)
        return 0
    while True:
        try:
            message = _read_message()
        except json.JSONDecodeError:
            continue
        if message is None:
            return 0
        reply = _handle(message)
        if reply is not None:
            _write_message(reply)


if __name__ == "__main__":
    raise SystemExit(main())

"""Chat intercept: write mixed-site code first, then hold for GPU PNGs."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

from common.logger import xlogger
from common.networking import get_sse_ping_interval
from endpoints.OAI.types.chat_completion import ChatCompletionRequest
from sse_starlette import EventSourceResponse, ServerSentEvent

from images.jobs import (
    active_mcp_image_job,
    copy_job_to_workspace,
    get_mcp_image_job,
    launch_mcp_image_job,
    note_coding_progress,
    start_mcp_image_job,
    wait_mcp_job_progress,
    wait_until_done,
)
from images.paths import (
    dest_fact_list,
    image_download_command,
    image_download_note,
    job_id_from_text,
    living_download_pairs,
    planned_dest_fact_list,
    tool_result_has_pngs,
)
from images.plan import ImageTurnPlan, classify_image_turn, plan_from_extracted

JOB_MARK = "tabby-image-job:"
STATUS_MARK = "tabby-image-status:"
HOLD_KEEPALIVE_S = 12.0
NO_MODEL_WRITE = "No model is loaded, so files were not written."
NO_TEMPLATE_WRITE = "Chat is disabled because no prompt template is set."
MAX_CODE_TURNS = 16
_ATTACHED_PROJECT_IMAGE_RE = re.compile(r"Attached project image:\s+`([^`]+)`")
FILE_WRITE_NAMES = (
    "write",
    "write_file",
    "write_to_file",
    "create_file",
    "strreplace",
    "search_replace",
    "replace_in_file",
    "apply_patch",
    "applypatch",
    "apply_diff",
    "edit_notebook",
    "edit_file",
)
READONLY_AGENTS = frozenset({"ask", "plan"})
_HERO_STEMS = frozenset(
    {"header", "hero", "banner", "hero-background", "hero_background"}
)
_EXPLICIT_NEW_RE = re.compile(
    r"(?is)(?:"
    r"qwen-image:|"
    r"\b(?:generate|draw|render|create)\s+"
    r"(?:(?:real|gpu|new)\s+)*"
    r"(?:an?\s+)?"
    r"(?:images?|pictures?|photos?|pics?)\b|"
    r"\b(?:redo|recreate)\b|"
    r"\breplace\s+the\s+(?:logo|hero(?:\s+(?:image|photo))?|header\s+(?:image|photo)|image|photo)\b|"
    r"\bnew\s+(?:logo|hero(?:\s+photo)?|header\s+photo)\b"
    r")"
)
_RASTER_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_NAMED_DEST_RE = re.compile(r"(?i)\bimages/([A-Za-z][A-Za-z0-9._-]*)")
_SKIP_DEST_STEMS = frozenset({"image", "images", "generated", "generated.png"})
_MIN_GPU_RASTER_BYTES = 50_000
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _readonly_agent(agent: str | None) -> bool:
    """UI Ask/Plan: inspect only. Do not start Comfy or write files."""
    return str(agent or "").strip().lower() in READONLY_AGENTS


def workspace_raster_paths(owner: str | None, chat_id: str | None) -> list[str]:
    """Relative image paths already in this UI Code workspace."""
    if not owner or not chat_id:
        return []
    try:
        from ui.workspace import IMAGE_SUFFIXES, list_files
    except Exception:
        return []
    try:
        rows = list_files(owner, chat_id)
    except Exception:
        return []
    suffixes = IMAGE_SUFFIXES or _RASTER_SUFFIXES
    found: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip().replace("\\", "/")
        if not path or _is_scratch_raster(path):
            continue
        try:
            size = int(row.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size and size < 1024:
            continue
        kind = str(row.get("kind") or "")
        if kind == "image" or Path(path).suffix.lower() in suffixes:
            found.append(path)
    return found


def _is_scratch_raster(path: str) -> bool:
    """Scratch leftovers are not dests for a new images/logo or header."""
    clean = str(path or "").replace("\\", "/").lstrip("/")
    return clean == "scratch" or clean.startswith("scratch/")


def _named_image_dests(text: str) -> list[str]:
    """Project dests the user named, such as images/logo or images/header."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _NAMED_DEST_RE.finditer(text or ""):
        raw = str(match.group(1) or "").strip()
        stem = Path(raw).stem.lower().replace("_", "-")
        if not stem or stem in _SKIP_DEST_STEMS:
            continue
        if stem in _HERO_STEMS:
            name = "header.png"
        elif Path(raw).suffix:
            name = Path(raw).name
        else:
            name = f"{stem}.png"
        dest = f"images/{name}"
        if dest in seen:
            continue
        seen.add(dest)
        found.append(dest)
    return found


def _workspace_gpu_raster(owner: str, chat_id: str, dest: str) -> bool:
    """True when this dest is a real GPU raster, not a stub or converted leftover."""
    wanted = str(dest or "").strip().replace("\\", "/").lstrip("/")
    if not wanted or _is_scratch_raster(wanted):
        return False
    try:
        from ui.workspace import resolve_file

        path = resolve_file(owner, chat_id, wanted)
    except (OSError, ValueError, FileNotFoundError):
        return False
    try:
        size = path.stat().st_size
        head = path.read_bytes()[:12]
    except OSError:
        return False
    if size < _MIN_GPU_RASTER_BYTES:
        return False
    suffix = Path(wanted).suffix.lower()
    if suffix == ".png":
        return head.startswith(_PNG_MAGIC)
    if suffix in {".jpg", ".jpeg"}:
        return head.startswith(_JPEG_MAGIC)
    if suffix == ".webp":
        return head.startswith(b"RIFF") and b"WEBP" in head
    if suffix == ".gif":
        return head.startswith(b"GIF8")
    return False


def _gpu_dest_ready(
    dest: str,
    existing: list[str],
    owner: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """Skip Comfy only when the named dest is already a real GPU file."""
    if owner and chat_id:
        return _workspace_gpu_raster(owner, chat_id, dest)
    return _dest_exists(dest, existing)


def _upgrade_missing_named_dests(
    plan: ImageTurnPlan,
    ask: str,
    existing: list[str],
    owner: str | None = None,
    chat_id: str | None = None,
) -> ImageTurnPlan:
    """Scratch leftovers are not reuse when images/logo or header is still missing."""
    if plan.action == "generate" and plan.items:
        return plan
    missing = [
        dest
        for dest in _named_image_dests(ask)
        if not _gpu_dest_ready(dest, existing, owner, chat_id)
    ]
    if not missing:
        return plan
    items = plan_from_extracted(ask, [{"filename": Path(dest).name} for dest in missing])
    if not items:
        return plan
    return ImageTurnPlan(action="generate", items=items, from_model=False)


def workspace_raster_facts(paths: list[str]) -> str:
    if not paths:
        return ""
    return "Already in the project: " + ", ".join(paths) + "."


def _raster_stem(path: str) -> str:
    return Path(str(path or "").replace("\\", "/")).stem.lower().replace("_", "-")


def _dest_exists(dest: str, existing: list[str]) -> bool:
    wanted = str(dest or "").strip().replace("\\", "/").lstrip("/")
    if not wanted or not existing:
        return False
    dest_name = Path(wanted).name.lower()
    dest_stem = _raster_stem(wanted)
    dest_suffix = Path(wanted).suffix.lower()
    dest_stems = {dest_stem}
    if dest_stem in _HERO_STEMS:
        dest_stems |= _HERO_STEMS
    for path in existing:
        have = str(path or "").strip().replace("\\", "/").lstrip("/")
        if not have:
            continue
        have_suffix = Path(have).suffix.lower()
        if dest_suffix and have_suffix and dest_suffix != have_suffix:
            continue
        if have == wanted or have.endswith("/" + wanted) or wanted.endswith("/" + have):
            return True
        name = Path(have).name.lower()
        if name == dest_name:
            return True
        stem = _raster_stem(have)
        if stem == dest_stem:
            return True
        if dest_stem in dest_stems and stem in dest_stems:
            return True
    return False


def _existing_raster_paths(
    job,
    workspace_paths: list[str],
    owner: str | None = None,
    chat_id: str | None = None,
) -> list[str]:
    found = list(workspace_paths)
    if job is None:
        return found
    for _url, dest in living_download_pairs(job):
        if not dest:
            continue
        if owner and chat_id:
            if _workspace_gpu_raster(owner, chat_id, dest):
                found.append(dest)
            continue
        found.append(dest)
    return found


def _all_dests_exist(
    items: list[dict[str, str]],
    existing: list[str],
    owner: str | None = None,
    chat_id: str | None = None,
) -> bool:
    dests = [str(row.get("output_path") or "").strip() for row in items or []]
    dests = [dest for dest in dests if dest]
    if not dests:
        return False
    if owner and chat_id:
        return all(_workspace_gpu_raster(owner, chat_id, dest) for dest in dests)
    if not existing:
        return False
    return all(_dest_exists(dest, existing) for dest in dests)


def _last_assistant_text(data: ChatCompletionRequest) -> str:
    for message in reversed(data.messages or []):
        if (message.role or "").lower() == "assistant":
            return _content_text(message.content)
    return ""


def _explicit_new_rasters(data: ChatCompletionRequest) -> bool:
    from common.phrase_switch import last_user_text, requested_image_prompt

    if requested_image_prompt(data, explicit_only=True):
        return True
    from ui.code_agent import is_build_prompt

    text = (last_user_text(data) or "").strip()
    if _EXPLICIT_NEW_RE.search(text):
        return True
    if is_build_prompt(text):
        return bool(_EXPLICIT_NEW_RE.search(_last_assistant_text(data) or ""))
    return False


def _classify_prior_facts(job, workspace_paths: list[str]) -> str:
    parts: list[str] = []
    if job and job.status in ("done", "error"):
        dests = dest_fact_list(living_download_pairs(job))
        if dests:
            parts.append(dests)
    raster = workspace_raster_facts(workspace_paths)
    if raster:
        parts.append(raster)
    return "\n".join(parts)


def _inject_existing_image_facts(
    data: ChatCompletionRequest, job, workspace_paths: list[str]
) -> None:
    if job:
        _inject_dest_facts(data, job)
    facts = workspace_raster_facts(workspace_paths)
    if facts:
        _append_user_facts(
            data,
            facts + " Use those local paths. Do not generate images.",
        )


def _content_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        text = getattr(part, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def last_role(data: ChatCompletionRequest) -> str:
    messages = data.messages or []
    if not messages:
        return ""
    return (messages[-1].role or "").lower()


def _history_blob(data: ChatCompletionRequest) -> str:
    parts: list[str] = []
    for message in data.messages or []:
        parts.append(_content_text(message.content))
        for call in message.tool_calls or []:
            args = getattr(getattr(call, "function", None), "arguments", "") or ""
            parts.append(str(args))
    return "\n".join(parts)


def job_id_from_history(data: ChatCompletionRequest) -> str:
    return job_id_from_text(_history_blob(data))


def _job_uses_curl(job) -> bool:
    dests = [getattr(item, "output_path", "") for item in (getattr(job, "items", None) or [])]
    return any(dest and dest != "images/generated.png" for dest in dests)


def _shell_name(data: ChatCompletionRequest) -> str:
    from common.image_paths import match_tool_name

    names: list[str] = []
    for spec in data.tools or []:
        func = getattr(spec, "function", None)
        name = getattr(func, "name", None) if func is not None else getattr(spec, "name", None)
        if name:
            names.append(str(name))
    return match_tool_name(names, ("shell", "bash", "run_in_terminal", "terminal")) or "Shell"


def _append_user_facts(data: ChatCompletionRequest, facts: str) -> None:
    if not facts:
        return
    for message in reversed(data.messages or []):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            if facts in content:
                return
            message.content = content.rstrip() + "\n" + facts
            return
        return


def _inject_dest_facts(data: ChatCompletionRequest, job) -> None:
    _append_user_facts(data, dest_fact_list(living_download_pairs(job)))


def _inject_planned_dests(data: ChatCompletionRequest, items: list[dict[str, str]]) -> None:
    _append_user_facts(data, planned_dest_fact_list(items))


def _assistant_message(response):
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    return getattr(choices[0], "message", None)


def _file_write_pairs(message) -> list[tuple[str, dict]]:
    from common.image_paths import match_tool_name

    return [
        (name, args)
        for name, args in _tool_call_pairs(message)
        if match_tool_name([name], FILE_WRITE_NAMES)
    ]


def _job_plan_items(job) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in getattr(job, "items", None) or []:
        dest = str(getattr(item, "output_path", "") or "").strip()
        if dest:
            items.append(
                {
                    "prompt": str(getattr(item, "prompt", "") or ""),
                    "output_path": dest,
                }
            )
    return items


def _keep_writing_page(code_response, job) -> bool:
    if not code_response:
        return False
    if not _file_write_pairs(_assistant_message(code_response)):
        return False
    return int(getattr(job, "code_turns", 0) or 0) < MAX_CODE_TURNS


def _first_code_pass_holds_llm(code_response) -> bool:
    """VS Code writes with its own tools. Prose or file tools both mean 'page first'."""
    if not code_response:
        return False
    message = _assistant_message(code_response)
    if message is None:
        return False
    if _file_write_pairs(message):
        return True
    return bool(str(getattr(message, "content", None) or "").strip())


def _tool_call_pairs(message) -> list[tuple[str, dict]]:
    pairs: list[tuple[str, dict]] = []
    for call in getattr(message, "tool_calls", None) or []:
        func = getattr(call, "function", None)
        name = getattr(func, "name", None) if func is not None else None
        if not name:
            continue
        raw = getattr(func, "arguments", "") or ""
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"arguments": raw}
            args = parsed if isinstance(parsed, dict) else {"value": parsed}
        pairs.append((str(name), args))
    return pairs


def _stamp_job_content(content: Optional[str], job) -> str:
    mark = f"{JOB_MARK} {job.id}"
    body = (content or "").strip()
    if JOB_MARK in body:
        return body
    if body:
        return f"{mark}\n{body}"
    return mark


def _items_finished(job) -> bool:
    items = list(getattr(job, "items", None) or [])
    if not items:
        return str(getattr(job, "status", "") or "") in ("done", "error")
    return all(
        str(getattr(item, "status", "") or "") in ("done", "error") for item in items
    )


def _editor_files_ready(job) -> bool:
    status = str(getattr(job, "status", "") or "")
    if status in ("done", "error"):
        return True
    if not _items_finished(job):
        return False
    items = list(getattr(job, "items", None) or [])
    if items and all(
        str(getattr(item, "status", "") or "") == "error" for item in items
    ):
        return True
    return bool(living_download_pairs(job))


def _hold_is_ready(job, *, files_only: bool) -> bool:
    status = str(getattr(job, "status", "") or "")
    if status in ("done", "error"):
        return True
    if files_only:
        return _editor_files_ready(job)
    return False


async def _wait_for_hold(job, *, files_only: bool) -> None:
    while not _hold_is_ready(job, files_only=files_only):
        await wait_mcp_job_progress(job, HOLD_KEEPALIVE_S)


def _job_dests(job) -> list[str]:
    from images.paths import safe_rel_png_path

    pairs = living_download_pairs(job)
    if pairs:
        return [dest for _url, dest in pairs]
    dests: list[str] = []
    for item in getattr(job, "items", None) or []:
        dest = safe_rel_png_path(getattr(item, "output_path", "") or "")
        if dest:
            dests.append(dest)
    return dests


def _message_has_curl(message) -> bool:
    if "curl " in _content_text(getattr(message, "content", None)):
        return True
    for _name, args in _tool_call_pairs(message):
        blob = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
        if "curl " in blob:
            return True
    return False


def _last_assistant_message(data: ChatCompletionRequest):
    for message in reversed(data.messages or []):
        if (message.role or "").lower() == "assistant":
            return message
    return None


def _last_assistant_was_curl(data: ChatCompletionRequest) -> bool:
    message = _last_assistant_message(data)
    return bool(message and _message_has_curl(message))


def _curl_assistant_count(data: ChatCompletionRequest) -> int:
    count = 0
    for message in reversed(data.messages or []):
        role = (message.role or "").lower()
        if role in ("tool", "function"):
            continue
        if role == "assistant":
            if _message_has_curl(message):
                count += 1
                continue
            break
        break
    return count


def _trailing_tool_blob(data: ChatCompletionRequest) -> str:
    parts: list[str] = []
    for message in reversed(data.messages or []):
        if (message.role or "").lower() not in ("tool", "function"):
            break
        parts.append(_content_text(message.content))
    return "\n".join(reversed(parts))


def _curl_tool_followup(data: ChatCompletionRequest, job, *, console: bool):
    from common.phrase_switch import text_response

    if console or job is None:
        return None
    if not _last_assistant_was_curl(data):
        return None
    status = str(getattr(job, "status", "") or "")
    if not _editor_files_ready(job) and status not in ("done", "error"):
        return None
    dests = _job_dests(job)
    mark = f"{JOB_MARK} {job.id}"
    if not dests:
        err = getattr(job, "error", None) or (
            "Image generation finished with no files on this host."
        )
        return text_response(data, f"{mark}\n{err}")
    blob = _trailing_tool_blob(data)
    if tool_result_has_pngs(blob, dests):
        return text_response(data, f"{mark}\nImages saved to {', '.join(dests)}.")
    if _curl_assistant_count(data) >= 2:
        return text_response(
            data,
            f"{mark}\nCould not download {', '.join(dests)}. "
            "The PNGs are on the GPU host; download those URLs by hand.",
        )
    return _curl_response(data, job)


async def _write_site_code(data: ChatCompletionRequest, disconnect_handler):
    """One coding completion while the LLM is still loaded. None if it cannot run."""
    from common import model
    from common.assistant_text import strip_response_apologies
    from common.networking import DisconnectHandler, generation_request
    from endpoints.OAI.utils.chat_completion import (
        apply_chat_template,
        generate_chat_completion,
    )

    container = getattr(model, "container", None)
    if not container or not getattr(container, "loaded", False):
        xlogger.info("Mixed chat code pass skipped: no loaded model")
        return None
    if getattr(container, "prompt_template", None) is None:
        return None
    model_path = getattr(container, "model_dir", None)
    if model_path is None:
        return None
    request = generation_request(
        getattr(disconnect_handler, "request", None) if disconnect_handler else None
    )
    nested = DisconnectHandler(
        request=request,
        description="mixed site code",
        abort_event=getattr(disconnect_handler, "abort_event", None),
    )
    try:
        sync = data.model_copy(update={"stream": False, "n": 1})
        prompt, embeddings = await apply_chat_template(sync)
        response = await generate_chat_completion(
            prompt, embeddings, sync, request, model_path, nested
        )
        return strip_response_apologies(response)
    except Exception as exc:
        xlogger.warning(f"Mixed chat code pass failed: {exc}")
        return None


async def _start_mixed_job(
    items: list[dict[str, str]],
    api_base: str,
    *,
    start: bool = True,
    owner: str | None = None,
    chat_id: str | None = None,
):
    job, kind = await start_mcp_image_job(
        items=items,
        seed=None,
        restore=True,
        api_base=api_base or "",
        delay=0.0,
        start=start,
        owner=owner,
        chat_id=chat_id,
    )
    xlogger.info(f"Mixed chat queued image job {job.id} ({kind}, {len(items)} dests)")
    return job


async def _launch_mixed_job(job):
    launched = await launch_mcp_image_job(job)
    xlogger.info(f"Mixed chat started Comfy for job {job.id}")
    return launched


async def _start_prompt_job(
    prompt: str,
    api_base: str,
    *,
    restore: bool,
    source_image=None,
    denoise=None,
    owner: str | None = None,
    chat_id: str | None = None,
):
    item: dict = {"prompt": prompt, "output_path": "images/generated.png"}
    if source_image is not None:
        item["source_image"] = str(Path(source_image))
    if denoise is not None:
        item["denoise"] = denoise
    items = [item]
    job, kind = await start_mcp_image_job(
        items=items,
        seed=None,
        restore=restore,
        api_base=api_base or "",
        delay=0.0,
        owner=owner,
        chat_id=chat_id,
    )
    xlogger.info(f"Chat image job {job.id} ({kind})")
    return job


def _code_reply(data: ChatCompletionRequest, job, code_response):
    from common.phrase_switch import text_response, tool_call_response

    message = _assistant_message(code_response)
    if message is None:
        return text_response(data, f"{JOB_MARK} {job.id}")
    content = _stamp_job_content(getattr(message, "content", None), job)
    if content == f"{JOB_MARK} {job.id}":
        content = (
            f"{content}\nWrite the page now. Images are rendering on the GPU; "
            "the next reply is the download curl."
        )
    calls = _tool_call_pairs(message)
    if calls:
        return tool_call_response(data, calls, content=content)
    return text_response(data, content)


def _curl_response(data: ChatCompletionRequest, job, code_response=None):
    from common.phrase_switch import text_response, tool_call_response

    pairs = living_download_pairs(job)
    mark = f"{JOB_MARK} {job.id}"
    parts = [mark]
    code_message = _assistant_message(code_response) if code_response else None
    code_content = getattr(code_message, "content", None) if code_message else None
    if isinstance(code_content, str) and code_content.strip():
        if JOB_MARK not in code_content:
            parts.append(code_content.strip())
        elif code_content.strip() != mark:
            parts = [code_content.strip()]
    if not pairs:
        err = job.error or "Image generation finished with no files on this host."
        parts.append(err)
        calls = _tool_call_pairs(code_message) if code_message else []
        body = "\n".join(parts)
        if calls:
            return tool_call_response(data, calls, content=body)
        return text_response(data, body)
    parts.append(image_download_note(pairs))
    command = image_download_command(pairs)
    calls = _tool_call_pairs(code_message) if code_message else []
    if command:
        calls.append((_shell_name(data), {"command": command}))
    body = "\n".join(parts)
    if calls:
        return tool_call_response(data, calls, content=body)
    return text_response(data, body)


def job_progress_line(job) -> str:
    """Short live status for the management UI (and SSE comments)."""
    phase = str(getattr(job, "phase", "") or getattr(job, "status", "") or "")
    count = int(getattr(job, "count", 0) or 0)
    index = int(getattr(job, "current_index", 0) or 0) + 1
    if phase == "queued":
        return "Queued"
    if phase in ("writing_code", "coding"):
        return "Planning the picture"
    if phase == "starting_comfy":
        return "Starting Comfy"
    if phase in ("generating", "running"):
        if count > 1:
            return f"Rendering image {min(index, count)} of {count}"
        return "Rendering in Comfy"
    if phase == "restoring_llm":
        return "Reloading the coding model"
    if str(getattr(job, "status", "") or "") == "error":
        return "Image generation failed"
    return ""


def _console_ready_text(
    job,
    api_base: Optional[str],
    *,
    code: bool = False,
    extra_files: Optional[list[str]] = None,
) -> str:
    from common.phrase_switch import image_job_done_text

    pairs = living_download_pairs(job)
    n = len(pairs)
    lead = "Here's the picture." if n == 1 else f"Here are the {n} pictures."
    lines = [lead, ""]
    for url, dest in pairs:
        label = dest if code and dest else ""
        lines.append(f"![{label}]({url})")
        lines.append("")
    lines.append(image_job_done_text(job=job, count=max(1, n)))
    if code:
        dests = [dest for _url, dest in pairs]
        names = []
        workspace_files = list(extra_files) if extra_files is not None else dests
        for name in workspace_files:
            if name and name not in names:
                names.append(name)
        if names:
            lines.append("They're also in this chat's Files: " + ", ".join(names) + ".")
        else:
            lines.append("It's also in Gallery and in this chat's Files.")
    else:
        lines.append(
            "It's also in Gallery. Describe another picture to generate it, "
            "or switch models from Status."
        )
    return "\n".join(lines).strip()


def _copy_workspace_pngs(job, workspace) -> list[str]:
    copied = copy_job_to_workspace(job)
    if copied:
        return copied
    if not workspace:
        return []
    owner, chat_id = workspace
    if not owner or not chat_id:
        return []
    if not str(getattr(job, "chat_id", "") or "").strip():
        job.chat_id = chat_id
    if not str(getattr(job, "owner", "") or "").strip():
        job.owner = owner
    return copy_job_to_workspace(job)


def _url_response(
    data: ChatCompletionRequest,
    job,
    api_base: Optional[str],
    *,
    console: bool = False,
    code: bool = False,
    extra_files: Optional[list[str]] = None,
):
    from common.phrase_switch import image_ready_response, text_response

    pairs = living_download_pairs(job)
    mark = f"{JOB_MARK} {job.id}"
    if not pairs:
        err = job.error or "Image generation finished with no files on this host."
        if console:
            return text_response(data, err)
        return text_response(data, f"{mark}\n{err}")
    if console:
        return text_response(
            data,
            _console_ready_text(job, api_base, code=code, extra_files=extra_files),
        )
    names = [url.rsplit("/", 1)[-1].split("?", 1)[0] for url, _dest in pairs]
    response = image_ready_response(
        data,
        names[-1],
        api_base=api_base,
        restore=bool(job.restore),
        count=len(names),
        filenames=names,
    )
    message = response.choices[0].message
    body = message.content or ""
    if JOB_MARK not in body:
        message.content = f"{mark}\n{body}"
    return response


async def _hold_then_reply(
    data: ChatCompletionRequest,
    job,
    *,
    mixed: bool,
    api_base: Optional[str],
    code_response=None,
    console: bool = False,
    workspace=None,
    extra_files: Optional[list[str]] = None,
):
    from common.phrase_switch import stream_chat_delta, stream_text, stream_tool_calls

    sync = data.model_copy(update={"stream": False})
    mixed = False if console else mixed
    code = bool(workspace)
    files_only = not console

    def _reply():
        copied = _copy_workspace_pngs(job, workspace)
        names = list(extra_files or []) + copied
        if mixed:
            return _curl_response(sync, job, code_response)
        return _url_response(
            sync, job, api_base, console=console, code=code, extra_files=names
        )

    async def _body():
        chunk_id = f"chatcmpl-{uuid4().hex}"
        created = int(time.time())
        yield ServerSentEvent(comment=f"{JOB_MARK} {job.id}")
        last_line = job_progress_line(job)
        if last_line:
            yield ServerSentEvent(comment=f"{STATUS_MARK} {last_line}")
        if not console:
            first = (last_line + "\n") if last_line else " "
            yield stream_chat_delta(
                data,
                {"role": "assistant", "content": first},
                chunk_id=chunk_id,
                created=created,
            )
        while not _hold_is_ready(job, files_only=files_only):
            await wait_mcp_job_progress(job, HOLD_KEEPALIVE_S)
            line = job_progress_line(job)
            if line and line != last_line:
                last_line = line
                yield ServerSentEvent(comment=f"{STATUS_MARK} {line}")
                if not console:
                    yield stream_chat_delta(
                        data,
                        {"content": line + "\n"},
                        chunk_id=chunk_id,
                        created=created,
                    )
            elif not console:
                yield stream_chat_delta(
                    data, {"content": " "}, chunk_id=chunk_id, created=created
                )
        reply = _reply()
        message = reply.choices[0].message
        if message.tool_calls:
            async for chunk in stream_tool_calls(
                data, message, chunk_id=chunk_id, created=created
            ):
                yield chunk
        else:
            async for chunk in stream_text(
                data, message.content or "", chunk_id=chunk_id, created=created
            ):
                yield chunk

    if data.stream:
        return EventSourceResponse(
            _body(),
            ping=get_sse_ping_interval(),
            sep="\n",
        )
    if console:
        await wait_until_done(job)
    else:
        await _wait_for_hold(job, files_only=True)
    return _reply()




def _attached_project_image_rel(text: str) -> str:
    matches = _ATTACHED_PROJECT_IMAGE_RE.findall(text or "")
    return str(matches[-1]).strip() if matches else ""


def _resolve_edit_source(source_image, owner: str | None, chat_id: str | None, text: str):
    if source_image is not None:
        path = Path(source_image)
        if path.is_file():
            return path
    rel = _attached_project_image_rel(text)
    if rel and owner and chat_id:
        from ui.workspace import resolve_file

        try:
            return resolve_file(owner, chat_id, rel)
        except ValueError:
            return None
    return None


async def handle(
    data: ChatCompletionRequest,
    api_base: Optional[str] = None,
    *,
    source_image=None,
    llm_ready: bool = True,
    gpu_is_comfy: bool = False,
    disconnect_handler=None,
    console: bool = False,
    owner: str | None = None,
    code: bool = False,
    chat_id: str | None = None,
    agent: str = "agent",
):
    """Mixed generate writes the page first, then holds until PNGs exist.

    File-write tool calls go out while the LLM stays loaded. Comfy starts
    only after a coding turn has no more file tools, and only when this
    turn explicitly asks for new rasters. Existing workspace or job dests
    are reuse. Always wins over the 9B while this conversation's job is
    still running. Resume only via ``tabby-image-job: <uuid>`` in this
    conversation — never by attaching a global coding job.

    console=True (management UI) still generates images but never emits
    a download curl. code=True plus a workspace copies finished PNGs into
    the per-chat host folder after the browser writes the page.

    agent=ask|plan (UI Code mode) does not start a new Comfy job. In-flight
    jobs still hold until they finish.
    """
    from common.phrase_switch import (
        IMAGE_GEN_RE,
        border_edit_prompt,
        last_user_text,
        refuses_new_images,
        requested_image_prompt,
        text_response,
        wants_border_trim,
    )

    workspace = (owner, chat_id) if code and owner and chat_id else None
    job_id = job_id_from_history(data)
    job = get_mcp_image_job(job_id) if job_id else None
    role = last_role(data)

    if job and role in ("tool", "function"):
        follow = _curl_tool_followup(data, job, console=console)
        if follow is not None:
            return follow

    if job and job.status in ("queued", "running"):
        if workspace:
            bound_owner, bound_chat = workspace
            if bound_owner and (not job.owner or job.owner == bound_owner):
                job.owner = bound_owner
            if bound_chat and (not job.chat_id or job.chat_id == bound_chat):
                job.chat_id = bound_chat
        return await _hold_then_reply(
            data,
            job,
            mixed=False if console else _job_uses_curl(job),
            api_base=api_base,
            console=console,
            workspace=workspace,
        )

    if job and job.status == "coding" and llm_ready:
        if workspace:
            _inject_planned_dests(data, _job_plan_items(job))
            note_coding_progress(job)
            code_response = await _write_site_code(data, disconnect_handler)
            if _keep_writing_page(code_response, job):
                return _code_reply(data, job, code_response)
            await _launch_mixed_job(job)
            if code_response and _file_write_pairs(_assistant_message(code_response)):
                return _code_reply(data, job, code_response)
            return await _hold_then_reply(
                data,
                job,
                mixed=True,
                api_base=api_base,
                code_response=code_response,
                console=True,
                workspace=workspace,
            )
        if console:
            await _launch_mixed_job(job)
            return await _hold_then_reply(
                data, job, mixed=False, api_base=api_base, console=True
            )
        _inject_planned_dests(data, _job_plan_items(job))
        note_coding_progress(job)
        code_response = await _write_site_code(data, disconnect_handler)
        if _keep_writing_page(code_response, job):
            return _code_reply(data, job, code_response)
        await _launch_mixed_job(job)
        if code_response and _file_write_pairs(_assistant_message(code_response)):
            return _code_reply(data, job, code_response)
        return await _hold_then_reply(
            data,
            job,
            mixed=True,
            api_base=api_base,
            code_response=code_response,
            console=console,
        )

    if role in ("tool", "function"):
        if job and job.status in ("done", "error"):
            _inject_dest_facts(data, job)
        return None

    if _readonly_agent(agent):
        return None

    ask = last_user_text(data) or ""
    if wants_border_trim(ask):
        source = _resolve_edit_source(source_image, owner, chat_id, ask)
        if source is not None:
            started = await _start_prompt_job(
                border_edit_prompt(ask),
                api_base or "",
                restore=bool(llm_ready),
                source_image=source,
                denoise=0.85,
                owner=owner,
                chat_id=chat_id if workspace else None,
            )
            return await _hold_then_reply(
                data,
                started,
                mixed=False,
                api_base=api_base,
                console=console,
                workspace=workspace,
            )

    if refuses_new_images(ask) and not IMAGE_GEN_RE.match(ask):
        return None

    if llm_ready:
        rasters = workspace_raster_paths(owner, chat_id) if workspace else []
        prior = _classify_prior_facts(job, rasters)
        plan = await classify_image_turn(
            data, disconnect_handler=disconnect_handler, prior_facts=prior
        )
        existing = _existing_raster_paths(job, rasters, owner, chat_id)
        plan = _upgrade_missing_named_dests(plan, ask, existing, owner, chat_id)
        if plan.action == "reuse":
            _inject_existing_image_facts(data, job, rasters)
            return None
        if (
            plan.action == "generate"
            and plan.items
            and _all_dests_exist(plan.items, existing, owner, chat_id)
            and not _explicit_new_rasters(data)
        ):
            _inject_existing_image_facts(data, job, rasters)
            return None
        if plan.action == "generate" and plan.items:
            busy = active_mcp_image_job()
            if busy and not job_id:
                if busy.status == "coding":
                    return text_response(
                        data,
                        f"The stack is already writing a page for job {busy.id}. "
                        "Wait until that chat finishes, then ask again.",
                    )
                return text_response(
                    data,
                    f"The GPU is already generating job {busy.id}. "
                    "Wait until that batch finishes, then ask again.",
                )
            if workspace:
                _inject_planned_dests(data, plan.items)
                code_response = await _write_site_code(data, disconnect_handler)
                keep = _first_code_pass_holds_llm(code_response)
                started = await _start_mixed_job(
                    plan.items,
                    api_base or "",
                    start=not keep,
                    owner=owner,
                    chat_id=chat_id,
                )
                if keep:
                    return _code_reply(data, started, code_response)
                return await _hold_then_reply(
                    data,
                    started,
                    mixed=True,
                    api_base=api_base,
                    code_response=code_response,
                    console=True,
                    workspace=workspace,
                )
            if console:
                started = await _start_mixed_job(
                    plan.items,
                    api_base or "",
                    start=True,
                    owner=owner,
                    chat_id=chat_id,
                )
                return await _hold_then_reply(
                    data, started, mixed=False, api_base=api_base, console=True
                )
            _inject_planned_dests(data, plan.items)
            code_response = await _write_site_code(data, disconnect_handler)
            keep = _first_code_pass_holds_llm(code_response)
            started = await _start_mixed_job(
                plan.items,
                api_base or "",
                start=not keep,
                owner=owner,
                chat_id=chat_id,
            )
            if keep:
                return _code_reply(data, started, code_response)
            return await _hold_then_reply(
                data,
                started,
                mixed=True,
                api_base=api_base,
                code_response=code_response,
                console=console,
            )

    explicit = requested_image_prompt(data, explicit_only=True)
    if llm_ready and explicit:
        started = await _start_prompt_job(
            explicit,
            api_base or "",
            restore=True,
            source_image=source_image,
            owner=owner,
            chat_id=chat_id if workspace else None,
        )
        return await _hold_then_reply(
            data,
            started,
            mixed=False,
            api_base=api_base,
            console=console,
            workspace=workspace,
        )

    if not llm_ready and gpu_is_comfy:
        prompt = requested_image_prompt(data)
        if not prompt and source_image is not None:
            from common.phrase_switch import last_user_text, looks_like_chat_not_image

            text = last_user_text(data).strip()
            if not looks_like_chat_not_image(text):
                prompt = text or "cartoon style"
        if prompt:
            started = await _start_prompt_job(
                prompt,
                api_base or "",
                restore=False,
                source_image=source_image,
                owner=owner,
                chat_id=chat_id if workspace else None,
            )
            return await _hold_then_reply(
                data,
                started,
                mixed=False,
                api_base=api_base,
                console=console,
                workspace=workspace,
            )

    if not llm_ready:
        if job and job.status == "coding":
            await _launch_mixed_job(job)
            return await _hold_then_reply(
                data, job, mixed=True, api_base=api_base, console=console
            )
        busy = active_mcp_image_job()
        if busy and busy.status in ("queued", "running"):
            return text_response(
                data,
                f"Images are still rendering (job {busy.id}). "
                "Wait for the download curl in the chat that started that job.",
            )

    return None

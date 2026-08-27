"""Chat intercept: write mixed-site code first, then hold for GPU PNGs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

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
    wait_until_done,
)
from images.paths import (
    dest_fact_list,
    image_download_command,
    image_download_note,
    job_id_from_text,
    living_download_pairs,
    planned_dest_fact_list,
)
from images.plan import classify_image_turn

JOB_MARK = "tabby-image-job:"
STATUS_MARK = "tabby-image-status:"
MAX_CODE_TURNS = 16
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
BUILD_PROMPT = "Implement the approved plan above. Do not wait for more confirmation."
_HERO_STEMS = frozenset(
    {"header", "hero", "banner", "hero-background", "hero_background"}
)
_EXPLICIT_NEW_RE = re.compile(
    r"(?is)(?:"
    r"qwen-image:|"
    r"\b(?:generate|draw|render)\s+an?\s+(?:image|picture|photo|pic)\b|"
    r"\b(?:redo|recreate)\b|"
    r"\breplace\s+the\s+(?:logo|hero(?:\s+(?:image|photo))?|header\s+(?:image|photo)|image|photo)\b|"
    r"\bnew\s+(?:logo|hero(?:\s+photo)?|header\s+photo)\b"
    r")"
)
_RASTER_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


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
        if not path:
            continue
        kind = str(row.get("kind") or "")
        if kind == "image" or Path(path).suffix.lower() in suffixes:
            found.append(path)
    return found


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
    dest_stems = {dest_stem}
    if dest_stem in _HERO_STEMS:
        dest_stems |= _HERO_STEMS
    for path in existing:
        have = str(path or "").strip().replace("\\", "/").lstrip("/")
        if not have:
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


def _existing_raster_paths(job, workspace_paths: list[str]) -> list[str]:
    found = list(workspace_paths)
    if job is None:
        return found
    for _url, dest in living_download_pairs(job):
        if dest:
            found.append(dest)
    return found


def _all_dests_exist(items: list[dict[str, str]], existing: list[str]) -> bool:
    dests = [str(row.get("output_path") or "").strip() for row in items or []]
    dests = [dest for dest in dests if dest]
    if not dests or not existing:
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
    text = (last_user_text(data) or "").strip()
    if _EXPLICIT_NEW_RE.search(text):
        return True
    if text == BUILD_PROMPT:
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


async def _write_site_code(data: ChatCompletionRequest, disconnect_handler):
    """One coding completion while the LLM is still loaded. None if it cannot run."""
    from common import model
    from common.assistant_text import strip_response_apologies
    from common.networking import DisconnectHandler
    from endpoints.OAI.utils.chat_completion import (
        apply_chat_template,
        generate_chat_completion,
    )

    request = getattr(disconnect_handler, "request", None) if disconnect_handler else None
    container = getattr(model, "container", None)
    if request is None or not container or not getattr(container, "loaded", False):
        xlogger.info("Mixed chat code pass skipped: no request or loaded model")
        return None
    if getattr(container, "prompt_template", None) is None:
        return None
    model_path = getattr(container, "model_dir", None)
    if model_path is None:
        return None
    state = getattr(request, "state", None)
    if state is None or not getattr(state, "id", None):
        xlogger.info("Mixed chat code pass skipped: request has no id")
        return None
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
    owner: str | None = None,
    chat_id: str | None = None,
):
    items = [{"prompt": prompt, "output_path": "images/generated.png"}]
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
    from common.phrase_switch import stream_text, stream_tool_calls

    sync = data.model_copy(update={"stream": False})
    mixed = False if console else mixed
    code = bool(workspace)

    async def _body():
        yield ServerSentEvent(comment=f"{JOB_MARK} {job.id}")
        line = job_progress_line(job)
        if line:
            yield ServerSentEvent(comment=f"{STATUS_MARK} {line}")
        await wait_until_done(job)
        copied = _copy_workspace_pngs(job, workspace)
        names = list(extra_files or []) + copied
        reply = (
            _curl_response(sync, job, code_response)
            if mixed
            else _url_response(
                sync, job, api_base, console=console, code=code, extra_files=names
            )
        )
        message = reply.choices[0].message
        if message.tool_calls:
            async for chunk in stream_tool_calls(data, message):
                yield chunk
        else:
            async for chunk in stream_text(data, message.content or ""):
                yield chunk

    if data.stream:
        return EventSourceResponse(
            _body(),
            ping=get_sse_ping_interval(),
            sep="\n",
        )
    await wait_until_done(job)
    copied = _copy_workspace_pngs(job, workspace)
    names = list(extra_files or []) + copied
    if mixed:
        return _curl_response(sync, job, code_response)
    return _url_response(
        sync, job, api_base, console=console, code=code, extra_files=names
    )


async def _stream_code_then_images(
    data: ChatCompletionRequest,
    *,
    api_base: Optional[str],
    disconnect_handler,
    owner: str,
    chat_id: str,
    items: Optional[list[dict[str, str]]] = None,
    job=None,
    agent: str = "agent",
):
    from common.phrase_switch import stream_text
    from ui.code_agent import final_code_text, iter_code_turns

    workspace = (owner, chat_id)
    sync = data.model_copy(update={"stream": False})
    start_new = bool(items) and not _readonly_agent(agent)

    async def _body():
        written: list[str] = []
        text = ""
        yield ServerSentEvent(comment=f"{STATUS_MARK} Updating project")
        async for event in iter_code_turns(
            sync, disconnect_handler, owner, chat_id, agent=agent
        ):
            kind = event[0]
            if kind == "status":
                yield ServerSentEvent(comment=f"{STATUS_MARK} {event[1]}")
            elif kind == "done":
                text = event[1] or ""
                written = list(event[2] or [])
        started = job
        if start_new:
            started = await _start_mixed_job(
                items, api_base or "", start=True, owner=owner, chat_id=chat_id
            )
        elif started is not None and getattr(started, "status", "") == "coding":
            if chat_id:
                started.chat_id = chat_id
            if owner:
                started.owner = owner
            await _launch_mixed_job(started)
        if started is not None:
            yield ServerSentEvent(comment=f"{JOB_MARK} {started.id}")
            line = job_progress_line(started)
            if line:
                yield ServerSentEvent(comment=f"{STATUS_MARK} {line}")
            await wait_until_done(started)
            copied = _copy_workspace_pngs(started, workspace)
            reply = _url_response(
                sync,
                started,
                api_base,
                console=True,
                code=True,
                extra_files=written + copied,
            )
            text = reply.choices[0].message.content or final_code_text(text, written)
        else:
            text = final_code_text(text, written)
        async for chunk in stream_text(data, text):
            yield chunk

    if data.stream:
        return EventSourceResponse(
            _body(),
            ping=get_sse_ping_interval(),
            sep="\n",
        )
    written: list[str] = []
    text = ""
    async for event in iter_code_turns(
        sync, disconnect_handler, owner, chat_id, agent=agent
    ):
        if event[0] == "done":
            text = event[1] or ""
            written = list(event[2] or [])
    started = job
    if start_new:
        started = await _start_mixed_job(
            items, api_base or "", start=True, owner=owner, chat_id=chat_id
        )
    elif started is not None and getattr(started, "status", "") == "coding":
        if chat_id:
            started.chat_id = chat_id
        if owner:
            started.owner = owner
        await _launch_mixed_job(started)
    if started is not None:
        await wait_until_done(started)
        copied = _copy_workspace_pngs(started, workspace)
        return _url_response(
            sync,
            started,
            api_base,
            console=True,
            code=True,
            extra_files=written + copied,
        )
    from common.phrase_switch import text_response as _text

    return _text(sync, final_code_text(text, written))


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
    Write/StrReplace tool calls unless code=True, which writes into a
    per-chat host workspace instead.

    agent=ask|plan (UI Code mode) does not start a new Comfy job. In-flight
    jobs still hold until they finish.
    """
    from common.phrase_switch import requested_image_prompt, text_response

    workspace = (owner, chat_id) if code and owner and chat_id else None
    job_id = job_id_from_history(data)
    job = get_mcp_image_job(job_id) if job_id else None
    role = last_role(data)

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
            return await _stream_code_then_images(
                data,
                api_base=api_base,
                disconnect_handler=disconnect_handler,
                owner=owner or "",
                chat_id=chat_id or "",
                job=job,
                agent=agent,
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

    if llm_ready:
        rasters = workspace_raster_paths(owner, chat_id) if workspace else []
        prior = _classify_prior_facts(job, rasters)
        plan = await classify_image_turn(
            data, disconnect_handler=disconnect_handler, prior_facts=prior
        )
        if plan.action == "reuse":
            _inject_existing_image_facts(data, job, rasters)
            return None
        existing = _existing_raster_paths(job, rasters)
        if (
            plan.action == "generate"
            and plan.items
            and _all_dests_exist(plan.items, existing)
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
                return await _stream_code_then_images(
                    data,
                    api_base=api_base,
                    disconnect_handler=disconnect_handler,
                    owner=owner or "",
                    chat_id=chat_id or "",
                    items=plan.items,
                    agent=agent,
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
            keep = bool(
                code_response
                and _file_write_pairs(_assistant_message(code_response))
            )
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

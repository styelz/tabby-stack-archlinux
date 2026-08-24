"""Chat intercept: write mixed-site code first, then hold for GPU PNGs."""

from __future__ import annotations

import json
from typing import Optional

from common.logger import xlogger
from common.networking import get_sse_ping_interval
from endpoints.OAI.types.chat_completion import ChatCompletionRequest
from sse_starlette import EventSourceResponse, ServerSentEvent

from images.jobs import (
    active_mcp_image_job,
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
    items: list[dict[str, str]], api_base: str, *, start: bool = True, owner: str | None = None
):
    job, kind = await start_mcp_image_job(
        items=items,
        seed=None,
        restore=True,
        api_base=api_base or "",
        delay=0.0,
        start=start,
        owner=owner,
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
):
    items = [{"prompt": prompt, "output_path": "images/generated.png"}]
    job, kind = await start_mcp_image_job(
        items=items,
        seed=None,
        restore=restore,
        api_base=api_base or "",
        delay=0.0,
        owner=owner,
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


def _console_ready_text(job, api_base: Optional[str]) -> str:
    from common.phrase_switch import image_job_done_text

    pairs = living_download_pairs(job)
    n = len(pairs)
    lead = "Here's the picture." if n == 1 else f"Here are the {n} pictures."
    lines = [lead, ""]
    for url, _dest in pairs:
        lines.append(f"![]({url})")
        lines.append("")
    lines.append(image_job_done_text(job=job, count=max(1, n)))
    lines.append(
        "It's also in Gallery. Describe another picture to generate it, "
        "or switch models from Status."
    )
    return "\n".join(lines).strip()


def _url_response(
    data: ChatCompletionRequest,
    job,
    api_base: Optional[str],
    *,
    console: bool = False,
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
        return text_response(data, _console_ready_text(job, api_base))
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
):
    from common.phrase_switch import stream_text, stream_tool_calls

    sync = data.model_copy(update={"stream": False})
    mixed = False if console else mixed

    async def _body():
        yield ServerSentEvent(comment=f"{JOB_MARK} {job.id}")
        line = job_progress_line(job)
        if line:
            yield ServerSentEvent(comment=f"{STATUS_MARK} {line}")
        await wait_until_done(job)
        reply = (
            _curl_response(sync, job, code_response)
            if mixed
            else _url_response(sync, job, api_base, console=console)
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
    if mixed:
        return _curl_response(sync, job, code_response)
    return _url_response(sync, job, api_base, console=console)


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
):
    """Mixed generate writes the page first, then holds until PNGs exist.

    File-write tool calls go out while the LLM stays loaded. Comfy starts
    only after a coding turn has no more file tools. Always wins over the
    9B while this conversation's job is still running.

    console=True (management UI) still generates images but never emits
    Write/StrReplace tool calls.
    """
    from common.phrase_switch import requested_image_prompt, text_response

    job_id = job_id_from_history(data)
    job = get_mcp_image_job(job_id) if job_id else None
    role = last_role(data)
    if not job and role in ("tool", "function") and llm_ready:
        busy = active_mcp_image_job()
        if busy and busy.status == "coding":
            job = busy

    if job and job.status in ("queued", "running"):
        return await _hold_then_reply(
            data,
            job,
            mixed=False if console else _job_uses_curl(job),
            api_base=api_base,
            console=console,
        )

    if job and job.status == "coding" and llm_ready:
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

    if llm_ready:
        prior = ""
        if job and job.status in ("done", "error"):
            prior = dest_fact_list(living_download_pairs(job))
        plan = await classify_image_turn(
            data, disconnect_handler=disconnect_handler, prior_facts=prior
        )
        if plan.action == "reuse":
            if job:
                _inject_dest_facts(data, job)
            return None
        if plan.action == "generate" and plan.items:
            busy = active_mcp_image_job()
            if busy and not job_id:
                return text_response(
                    data,
                    f"The GPU is already generating job {busy.id}. "
                    "Wait until that batch finishes, then ask again.",
                )
            if console:
                started = await _start_mixed_job(plan.items, api_base or "", start=True, owner=owner)
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
                plan.items, api_base or "", start=not keep, owner=owner
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
            explicit, api_base or "", restore=True, source_image=source_image, owner=owner
        )
        return await _hold_then_reply(
            data, started, mixed=False, api_base=api_base, console=console
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
                prompt, api_base or "", restore=False, source_image=source_image, owner=owner
            )
            return await _hold_then_reply(
                data, started, mixed=False, api_base=api_base, console=console
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

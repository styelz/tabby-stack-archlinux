"""Chat intercept: hold POST /v1/chat/completions until GPU PNGs exist."""

from __future__ import annotations

from typing import Optional

from common.logger import xlogger
from common.networking import get_sse_ping_interval
from endpoints.OAI.types.chat_completion import ChatCompletionRequest
from sse_starlette import EventSourceResponse, ServerSentEvent

from images.jobs import (
    active_mcp_image_job,
    get_mcp_image_job,
    start_mcp_image_job,
    wait_until_done,
)
from images.paths import (
    dest_fact_list,
    image_download_command,
    image_download_note,
    job_id_from_text,
    living_download_pairs,
)
from images.plan import classify_image_turn

JOB_MARK = "tabby-image-job:"


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


def _inject_dest_facts(data: ChatCompletionRequest, job) -> None:
    from common.phrase_switch import QUERY_TAG_RE

    facts = dest_fact_list(living_download_pairs(job))
    if not facts:
        return
    for message in reversed(data.messages or []):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            if facts in content:
                return
            if QUERY_TAG_RE.search(content):
                message.content = content.rstrip() + "\n" + facts
            else:
                message.content = content.rstrip() + "\n" + facts
            return
        return


async def _start_mixed_job(items: list[dict[str, str]], api_base: str):
    job, kind = await start_mcp_image_job(
        items=items,
        seed=None,
        restore=True,
        api_base=api_base or "",
        delay=0.0,
    )
    xlogger.info(f"Mixed chat queued image job {job.id} ({kind}, {len(items)} dests)")
    return job


async def _start_prompt_job(
    prompt: str,
    api_base: str,
    *,
    restore: bool,
    source_image=None,
):
    items = [{"prompt": prompt, "output_path": "images/generated.png"}]
    job, kind = await start_mcp_image_job(
        items=items,
        seed=None,
        restore=restore,
        api_base=api_base or "",
        delay=0.0,
    )
    xlogger.info(f"Chat image job {job.id} ({kind})")
    return job


def _curl_response(data: ChatCompletionRequest, job):
    from common.phrase_switch import text_response, tool_call_response

    pairs = living_download_pairs(job)
    mark = f"{JOB_MARK} {job.id}"
    if not pairs:
        err = job.error or "Image generation finished with no files on this host."
        return text_response(data, f"{mark}\n{err}")
    note = f"{mark}\n{image_download_note(pairs)}"
    command = image_download_command(pairs)
    if not command:
        return text_response(data, note)
    name = _shell_name(data)
    return tool_call_response(
        data,
        [(name, {"command": command})],
        content=note,
    )


def _url_response(data: ChatCompletionRequest, job, api_base: Optional[str]):
    from common.phrase_switch import image_ready_response, text_response

    pairs = living_download_pairs(job)
    mark = f"{JOB_MARK} {job.id}"
    if not pairs:
        err = job.error or "Image generation finished with no files on this host."
        return text_response(data, f"{mark}\n{err}")
    filename = pairs[-1][0].rsplit("/", 1)[-1].split("?", 1)[0]
    response = image_ready_response(
        data, filename, api_base=api_base, restore=bool(job.restore), count=len(pairs)
    )
    message = response.choices[0].message
    body = message.content or ""
    if JOB_MARK not in body:
        message.content = f"{mark}\n{body}"
    return response


async def _hold_then_reply(data: ChatCompletionRequest, job, *, mixed: bool, api_base: Optional[str]):
    from common.phrase_switch import stream_text, stream_tool_calls

    sync = data.model_copy(update={"stream": False})

    async def _body():
        yield ServerSentEvent(comment=f"{JOB_MARK} {job.id}")
        await wait_until_done(job)
        reply = (
            _curl_response(sync, job) if mixed else _url_response(sync, job, api_base)
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
        return _curl_response(sync, job)
    return _url_response(sync, job, api_base)


async def handle(
    data: ChatCompletionRequest,
    api_base: Optional[str] = None,
    *,
    source_image=None,
    llm_ready: bool = True,
    gpu_is_comfy: bool = False,
    disconnect_handler=None,
):
    """Hold this chat turn until PNGs exist, then curl (mixed) or return URLs.

    Returns None so the coding model can write HTML. Always wins over the 9B
    while this conversation's job is still running.
    """
    from common.phrase_switch import requested_image_prompt

    job_id = job_id_from_history(data)
    job = get_mcp_image_job(job_id) if job_id else None
    role = last_role(data)

    if job and job.status in ("queued", "running"):
        return await _hold_then_reply(
            data, job, mixed=_job_uses_curl(job), api_base=api_base
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
                from common.phrase_switch import text_response

                return text_response(
                    data,
                    f"The GPU is already generating job {busy.id}. "
                    "Wait until that batch finishes, then ask again.",
                )
            started = await _start_mixed_job(plan.items, api_base or "")
            return await _hold_then_reply(
                data, started, mixed=True, api_base=api_base
            )

    explicit = requested_image_prompt(data, explicit_only=True)
    if llm_ready and explicit:
        started = await _start_prompt_job(
            explicit, api_base or "", restore=True, source_image=source_image
        )
        return await _hold_then_reply(data, started, mixed=False, api_base=api_base)

    if not llm_ready and gpu_is_comfy:
        prompt = requested_image_prompt(data)
        if not prompt and source_image is not None:
            from common.phrase_switch import last_user_text

            prompt = last_user_text(data).strip() or "cartoon style"
        if prompt:
            started = await _start_prompt_job(
                prompt, api_base or "", restore=False, source_image=source_image
            )
            return await _hold_then_reply(
                data, started, mixed=False, api_base=api_base
            )
        return None

    return None

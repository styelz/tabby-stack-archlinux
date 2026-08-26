"""Console chat: LLM replies plus inline images. Code mode writes a jailed project."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, Request
from sse_starlette import EventSourceResponse, ServerSentEvent

from common import model
from common.assistant_text import strip_apology_sse, strip_response_apologies
from common.gpu_mode import public_api_base
from common.model import check_model_container
from common.networking import DisconnectHandler, get_sse_ping_interval
from common.phrase_switch import (
    comfy_chat_suggest_text,
    comfy_idle_response,
    gpu_is_comfy,
    handle_if_requested,
    last_user_text,
    llm_not_ready_response,
    looks_like_chat_not_image,
    requested_profile,
    should_yield_comfy_to_llm,
    start_switch,
    stream_text,
    switch_reply_text,
    text_response,
    yield_comfy_to_llm_response,
)
from common.tabby_config import config
from endpoints.OAI.types.chat_completion import ChatCompletionRequest
from endpoints.OAI.utils.chat_completion import (
    apply_chat_template,
    generate_chat_completion,
    stream_generate_chat_completion,
)
from common.pasted_images import materialize_pasted_images
from images.chat import STATUS_MARK, handle as handle_image_chat
from ui.manager import sanitize_chat_payload, sanitize_code_payload
from ui.occupancy import StackGate, queue_comment, wait_tick


def completion_request_from_payload(payload: dict[str, Any]) -> ChatCompletionRequest:
    fields: dict[str, Any] = {
        "messages": payload["messages"],
        "stream": payload.get("stream", True),
        "tools": None,
    }
    if payload.get("temperature") is not None:
        fields["temperature"] = payload["temperature"]
    if payload.get("max_tokens") is not None:
        fields["max_tokens"] = payload["max_tokens"]
    return ChatCompletionRequest(**fields)


def is_code_request(body: dict[str, Any]) -> bool:
    return str(body.get("mode") or "").strip().lower() == "code"


async def stream_code_only(
    data: ChatCompletionRequest,
    disconnect_handler,
    username: str,
    chat_id: str,
    agent: str = "agent",
):
    from ui.code_agent import final_code_text, iter_code_turns, normalize_agent

    kind = normalize_agent(agent)
    start = "Updating project"
    if kind == "ask":
        start = "Reading project"
    elif kind == "plan":
        start = "Planning"
    sync = data.model_copy(update={"stream": False})

    async def _body():
        text = ""
        written: list[str] = []
        yield ServerSentEvent(comment=f"{STATUS_MARK} {start}")
        async for event in iter_code_turns(
            sync, disconnect_handler, username, chat_id, agent=kind
        ):
            if event[0] == "status":
                yield ServerSentEvent(comment=f"{STATUS_MARK} {event[1]}")
            elif event[0] == "done":
                text = event[1] or ""
                written = list(event[2] or [])
        async for chunk in stream_text(data, final_code_text(text, written)):
            yield chunk

    if data.stream:
        return EventSourceResponse(
            _body(),
            ping=get_sse_ping_interval(),
            sep="\n",
        )
    text = ""
    written: list[str] = []
    async for event in iter_code_turns(
        sync, disconnect_handler, username, chat_id, agent=kind
    ):
        if event[0] == "done":
            text = event[1] or ""
            written = list(event[2] or [])
    return text_response(sync, final_code_text(text, written))


def _completion_text(result: Any) -> str:
    choices = getattr(result, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return str(getattr(message, "content", None) or "")


async def _iter_sse(response) -> Any:
    iterator = getattr(response, "body_iterator", None)
    if iterator is None:
        return
    try:
        async for item in iterator:
            yield item
    finally:
        closer = getattr(iterator, "aclose", None)
        if closer is not None:
            try:
                await closer()
            except Exception:
                pass


async def _run_console_work(
    request: Request,
    data: ChatCompletionRequest,
    username: str,
    chat_id: str,
    code: bool,
    saved_images: list,
    api_base: str,
    disconnect_handler,
    agent: str = "agent",
):
    llm_ready = bool(model.container and getattr(model.container, "loaded", False))
    await disconnect_handler.poll()
    name = requested_profile(data)
    if name:
        start_switch(name)
        return text_response(data, switch_reply_text(name))
    image_response = await handle_image_chat(
        data,
        api_base,
        source_image=saved_images[-1] if saved_images else None,
        llm_ready=llm_ready,
        gpu_is_comfy=gpu_is_comfy(),
        disconnect_handler=disconnect_handler,
        console=True,
        owner=username or None,
        code=code,
        chat_id=chat_id or None,
    )
    if image_response is not None:
        return image_response
    if not llm_ready:
        if gpu_is_comfy():
            if looks_like_chat_not_image(last_user_text(data)):
                return text_response(data, comfy_chat_suggest_text())
            if should_yield_comfy_to_llm(data):
                return await yield_comfy_to_llm_response(data, console=True)
            return await comfy_idle_response(data, api_base=api_base)
        return await llm_not_ready_response(data, console=True)

    if code and chat_id:
        return await stream_code_only(
            data, disconnect_handler, username, chat_id, agent=agent
        )

    await check_model_container()
    if not (model.container and getattr(model.container, "model_dir", None)):
        raise HTTPException(503, "No model is loaded.")
    if getattr(model.container, "prompt_template", None) is None:
        raise HTTPException(422, "Chat is disabled because no prompt template is set.")

    model_path = model.container.model_dir
    prompt, mm_embeddings = await apply_chat_template(data)
    try:
        await disconnect_handler.poll()
        streaming = bool(data.stream)
        disabled = bool(getattr(config.developer, "disable_request_streaming", False))
        if streaming and not disabled:
            model.check_context_length(prompt, data, mm_embeddings)
            return EventSourceResponse(
                strip_apology_sse(
                    stream_generate_chat_completion(
                        prompt, mm_embeddings, data, request, model_path, disconnect_handler
                    )
                ),
                ping=get_sse_ping_interval(),
                sep="\n",
            )
        response = await generate_chat_completion(
            prompt, mm_embeddings, data, request, model_path, disconnect_handler
        )
        return strip_response_apologies(response)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc


async def _stream_held_result(gate: StackGate, result):
    try:
        async for item in _iter_sse(result):
            yield item
    finally:
        await gate.release()


async def _queued_console_events(
    request: Request,
    data: ChatCompletionRequest,
    username: str,
    chat_id: str,
    code: bool,
    saved_images: list,
    api_base: str,
    disconnect_handler,
    gate: StackGate,
    first_info: dict[str, Any],
    agent: str = "agent",
):
    try:
        info: dict[str, Any] | None = first_info
        while info is not None:
            yield ServerSentEvent(comment=queue_comment(info))
            await wait_tick(1.0)
            info = await gate.step(disconnect_handler)
        result = await _run_console_work(
            request,
            data,
            username,
            chat_id,
            code,
            saved_images,
            api_base,
            disconnect_handler,
            agent,
        )
        if isinstance(result, EventSourceResponse):
            async for item in _iter_sse(result):
                yield item
            return
        text = _completion_text(result)
        if text:
            async for chunk in stream_text(data, text):
                yield chunk
    except HTTPException as exc:
        yield ServerSentEvent(data=json.dumps({"error": {"message": str(exc.detail)}}))
    finally:
        await gate.release()


def _sse(content):
    return EventSourceResponse(
        content,
        ping=get_sse_ping_interval(),
        sep="\n",
    )


async def run_console_chat(request: Request, body: dict[str, Any], username: str = ""):
    code = is_code_request(body)
    try:
        payload = (
            sanitize_code_payload(body, username) if code else sanitize_chat_payload(body)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    chat_id = str(payload.get("chat_id") or "") if code else ""
    agent = str(payload.get("agent") or "agent") if code else "agent"
    data = completion_request_from_payload(payload)
    saved_images = materialize_pasted_images(data)
    api_base = public_api_base(request)
    switched = handle_if_requested(data, api_base=api_base, defer_switch=True)
    if switched is not None:
        return switched

    disconnect_handler = DisconnectHandler(request, "/v1/ui/chat")
    gate = StackGate(username, kind="code" if code else "chat")
    info = await gate.step(disconnect_handler)
    if info is None:
        try:
            result = await _run_console_work(
                request,
                data,
                username,
                chat_id,
                code,
                saved_images,
                api_base,
                disconnect_handler,
                agent,
            )
        except Exception:
            await gate.release()
            raise
        if isinstance(result, EventSourceResponse):
            return _sse(_stream_held_result(gate, result))
        await gate.release()
        return result

    if data.stream:
        return _sse(
            _queued_console_events(
                request,
                data,
                username,
                chat_id,
                code,
                saved_images,
                api_base,
                disconnect_handler,
                gate,
                info,
                agent,
            )
        )

    try:
        while True:
            info = await gate.step(disconnect_handler)
            if info is None:
                break
            await wait_tick(1.0)
        result = await _run_console_work(
            request,
            data,
            username,
            chat_id,
            code,
            saved_images,
            api_base,
            disconnect_handler,
            agent,
        )
    except Exception:
        await gate.release()
        raise
    if isinstance(result, EventSourceResponse):
        return _sse(_stream_held_result(gate, result))
    await gate.release()
    return result


run_console_chat = run_console_chat

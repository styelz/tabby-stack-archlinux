"""Console chat: LLM replies plus inline images, no file tools."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from sse_starlette import EventSourceResponse

from common import model
from common.assistant_text import strip_apology_sse, strip_response_apologies
from common.gpu_mode import public_api_base
from common.model import check_model_container
from common.networking import DisconnectHandler, get_sse_ping_interval
from common.phrase_switch import (
    comfy_idle_response,
    gpu_is_comfy,
    handle_if_requested,
    llm_not_ready_response,
    should_yield_comfy_to_llm,
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
from images.chat import handle as handle_image_chat
from ui.manager import sanitize_chat_payload


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


async def run_console_chat(request: Request, body: dict[str, Any], username: str = ""):
    try:
        payload = sanitize_chat_payload(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    data = completion_request_from_payload(payload)
    saved_images = materialize_pasted_images(data)
    api_base = public_api_base(request)
    switched = handle_if_requested(data, api_base=api_base)
    if switched is not None:
        return switched

    llm_ready = bool(model.container and getattr(model.container, "loaded", False))
    disconnect_handler = DisconnectHandler(request, "/v1/ui/chat")
    await disconnect_handler.poll()
    image_response = await handle_image_chat(
        data,
        api_base,
        source_image=saved_images[-1] if saved_images else None,
        llm_ready=llm_ready,
        gpu_is_comfy=gpu_is_comfy(),
        disconnect_handler=disconnect_handler,
        console=True,
        owner=username or None,
    )
    if image_response is not None:
        return image_response
    if not llm_ready:
        if gpu_is_comfy():
            if should_yield_comfy_to_llm(data):
                return await yield_comfy_to_llm_response(data, console=True)
            return await comfy_idle_response(data, api_base=api_base)
        return await llm_not_ready_response(data, console=True)

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


run_console_chat = run_console_chat

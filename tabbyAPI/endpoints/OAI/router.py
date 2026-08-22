import asyncio
from asyncio import CancelledError, InvalidStateError

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette import EventSourceResponse

from common import model
from common.auth import check_api_key
from common.debug_requests import (
    log_chat_completion_request,
    write_chat_completion_prompt_log,
)
from common.model import check_embeddings_container, check_model_container
from common.networking import (
    get_sse_ping_interval,
    handle_request_error,
    DisconnectHandler,
    run_with_request_disconnect,
)
from common.tabby_config import config
from common.logger import xlogger
from endpoints.OAI.types.completion import CompletionRequest, CompletionResponse
from endpoints.OAI.types.chat_completion import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from endpoints.OAI.types.embedding import EmbeddingsRequest, EmbeddingsResponse
from common.agent_loop import inject_loop_break
from common.assistant_text import strip_apology_sse, strip_response_apologies
from common.gpu_mode import public_api_base
from common.pasted_images import materialize_pasted_images
from common.phrase_switch import (
    MAX_IMAGE_PROMPT_CHARS,
    comfy_idle_response,
    gpu_is_comfy,
    handle_if_requested,
    image_ready_response,
    inject_clipboard_save_hint,
    inject_mixed_image_hint,
    last_user_text,
    llm_not_ready_response,
    prepare_mixed_image_turn,
    requested_image_count,
    requested_image_prompt,
    should_yield_comfy_to_llm,
    text_response,
    yield_comfy_to_llm_response,
)
from endpoints.OAI.utils.common_ import load_inline_model
from endpoints.OAI.utils.chat_completion import (
    apply_chat_template,
    generate_chat_completion,
    stream_generate_chat_completion,
)
from endpoints.OAI.utils.completion import (
    generate_completion,
    stream_generate_completion,
)
from endpoints.OAI.utils.embeddings import get_embeddings


api_name = "OAI"
router = APIRouter()
urls = {
    "Completions": "http://{host}:{port}/v1/completions",
    "Chat completions": "http://{host}:{port}/v1/chat/completions",
}

# Block when model is still loading while second inline load request comes in
load_lock: asyncio.Lock = asyncio.Lock()
# One Flux batch at a time; Cursor retries must not stack extra jobs
image_gen_lock: asyncio.Lock = asyncio.Lock()


def setup():
    return router


async def _chat_generate_images(data, image_prompt, source_image, api_base, *, restore: bool):
    """Generate from chat. restore=True hands the GPU back to the last LLM."""
    from common.gpu_mode import begin_image_turn, turn_images_ready
    from endpoints.core.image_jobs import generate_images_job

    count, flux_prompt = requested_image_count(image_prompt)
    try:
        async with image_gen_lock:
            begin_image_turn(image_prompt, force_new=False)
            have = turn_images_ready(image_prompt, count)
            if len(have) >= count:
                return image_ready_response(
                    data, have[-1].name, api_base=api_base, restore=restore, count=count
                )
            extra = await generate_images_job(
                flux_prompt,
                count=count - len(have),
                source_image=source_image if not have else None,
                restore=restore,
            )
            dest = extra[-1] if extra else (have[-1] if have else None)
        return image_ready_response(
            data, dest.name if dest else "", api_base=api_base, restore=restore, count=count
        )
    except Exception as exc:
        return text_response(data, f"Image generation failed: {exc}")


# Completions endpoint
@router.post(
    "/v1/completions",
    dependencies=[Depends(check_api_key)],
)
async def completion_request(request: Request, data: CompletionRequest) -> CompletionResponse:
    """
    Generates a completion from a prompt.

    If stream = true, this returns an SSE stream.
    """

    raw_json = await request.json()
    xlogger.debug("[ENDPOINT] /v1/completions", {"raw": raw_json})

    async with load_lock:
        if data.model:
            await load_inline_model(data.model, request)
        else:
            await check_model_container()
        model_path = model.container.model_dir

    # Prepare raw prompt (will be str or list[str])
    prompt = data.prompt

    # Set an empty JSON schema if the request wants a JSON response
    if data.response_format.type == "json":
        data.json_schema = {"type": "object"}

    # Also accept specific schema from response_format
    if data.response_format.type == "json_schema":
        data.json_schema = data.response_format.json_schema

    try:
        disconnect_handler = DisconnectHandler(request, "/v1/completions")
        await disconnect_handler.poll()

        if data.stream and not config.developer.disable_request_streaming:
            model.check_context_length(prompt, data)
            return EventSourceResponse(
                stream_generate_completion(prompt, data, request, model_path, disconnect_handler),
                ping=get_sse_ping_interval(),
                sep="\n",
            )
        else:
            response = await generate_completion(
                prompt, data, request, model_path, disconnect_handler
            )
            return response

    except (CancelledError, InvalidStateError) as ex:
        raise HTTPException(422, "/v1/completions request cancelled by user.") from ex


# Chat completions endpoint
@router.post(
    "/v1/chat/completions",
    dependencies=[Depends(check_api_key), Depends(log_chat_completion_request)],
)
async def chat_completion_request(
    request: Request, data: ChatCompletionRequest
) -> ChatCompletionResponse:
    """
    Generates a chat completion from a prompt.

    If stream = true, this returns an SSE stream.
    """

    raw_json = await request.json()
    xlogger.debug("[ENDPOINT] /v1/chat/completions", {"raw": raw_json})

    api_base = public_api_base(request)
    saved_images = materialize_pasted_images(data)
    switch_response = handle_if_requested(data, api_base=api_base)
    if switch_response is not None:
        return switch_response
    inject_clipboard_save_hint(data, api_base=api_base)
    inject_loop_break(data)

    llm_ready = bool(model.container and getattr(model.container, "loaded", False))
    source_image = saved_images[-1] if saved_images else None
    explicit_prompt = requested_image_prompt(data, explicit_only=True)
    busy = await prepare_mixed_image_turn(data, api_base)
    # After Comfy restores the LLM this must still win. Otherwise the model
    # invents "wait 5 minutes, the PNG will download automatically" and stops.
    # Mixed coding+images also start the job here so the 9B never submits it.
    if busy:
        return busy
    if llm_ready and explicit_prompt:
        return await _chat_generate_images(
            data, explicit_prompt, source_image, api_base, restore=True
        )
    if not llm_ready:
        if not gpu_is_comfy():
            return await llm_not_ready_response(data)
        if should_yield_comfy_to_llm(data):
            return await yield_comfy_to_llm_response(data)
        image_prompt = requested_image_prompt(data)
        if not image_prompt and source_image:
            image_prompt = last_user_text(data).strip() or "cartoon style"
            if len(image_prompt) > MAX_IMAGE_PROMPT_CHARS:
                image_prompt = "cartoon style"
        if image_prompt:
            return await _chat_generate_images(
                data, image_prompt, source_image, api_base, restore=False
            )
        return await comfy_idle_response(data, api_base=api_base)

    inject_mixed_image_hint(data, api_base=api_base)
    async with load_lock:
        if data.model:
            await load_inline_model(data.model, request)
        else:
            await check_model_container()
        if not (model.container and getattr(model.container, "model_dir", None)):
            if gpu_is_comfy():
                if should_yield_comfy_to_llm(data):
                    return await yield_comfy_to_llm_response(data)
                return await comfy_idle_response(data, api_base=api_base)
            return await llm_not_ready_response(data)
        model_path = model.container.model_dir

    # Prepare raw prompt
    if model.container.prompt_template is None:
        error_message = handle_request_error(
            "Chat completions are disabled because a prompt template is not set.",
            exc_info=False,
        ).error.message
        raise HTTPException(422, error_message)
    prompt, mm_embeddings = await apply_chat_template(data)
    await write_chat_completion_prompt_log(request, prompt)

    # Set an empty JSON schema if the request wants a JSON response
    if data.response_format.type == "json":
        data.json_schema = {"type": "object"}

    # Also accept specific schema from response_format
    if data.response_format.type == "json_schema":
        data.json_schema = data.response_format.json_schema

    try:
        disconnect_handler = DisconnectHandler(request, "/v1/chat/completions")
        await disconnect_handler.poll()

        if data.stream and not config.developer.disable_request_streaming:
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
        else:
            response = await generate_chat_completion(
                prompt, mm_embeddings, data, request, model_path, disconnect_handler
            )
            return strip_response_apologies(response)

    except (CancelledError, InvalidStateError) as ex:
        raise HTTPException(422, "/v1/chat/completions request cancelled by user.") from ex


# Embeddings endpoint
@router.post(
    "/v1/embeddings",
    dependencies=[Depends(check_api_key), Depends(check_embeddings_container)],
)
async def embeddings(request: Request, data: EmbeddingsRequest) -> EmbeddingsResponse:
    embeddings_task = asyncio.create_task(get_embeddings(data, request))
    response = await run_with_request_disconnect(
        request,
        embeddings_task,
        f"Embeddings request {request.state.id} cancelled",
    )

    return response

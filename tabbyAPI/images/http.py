"""OpenAI-shaped POST /v1/images/generations: wait until files exist."""

from __future__ import annotations

import base64
import time
from typing import Optional

from common.gpu_mode import public_api_base, public_image_url
from images.jobs import generate_images_job, loaded_tabby_name


async def generate_response(request, data):
    """Render, then return b64_json + url. Never return a job id to poll."""
    from fastapi import HTTPException

    was_llm = bool(loaded_tabby_name())
    restore = data.restore if data.restore is not None else was_llm
    api_base = public_api_base(request)
    items = None
    if data.images:
        items = [
            {
                "prompt": item.prompt,
                "size": item.size or data.size or "1024x1024",
                "seed": item.seed if item.seed is not None else data.seed,
                "count": max(1, min(int(item.n or 1), 4)),
            }
            for item in data.images
            if (item.prompt or "").strip()
        ]
    prompt = (data.prompt or "").strip()
    if not items and not prompt:
        raise HTTPException(400, "prompt is required")
    count = max(1, min(int(data.n or 1), 4))
    try:
        paths = await generate_images_job(
            prompt,
            size=data.size or "1024x1024",
            seed=data.seed,
            count=count,
            restore=restore,
            items=items,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc

    images = []
    for path in paths:
        raw = path.read_bytes()
        images.append(
            {
                "b64_json": base64.b64encode(raw).decode("ascii"),
                "url": public_image_url(path.name, api_base=api_base),
                "revised_prompt": None,
            }
        )
    from common.phrase_switch import image_job_wait_text
    from endpoints.core.types.gpu import ImageGenerationResponse

    wait_prompts = [item["prompt"] for item in items] if items else None
    wait = image_job_wait_text(
        prompt, restore=restore, count=count, prompts=wait_prompts
    )
    return ImageGenerationResponse(
        created=int(time.time()),
        data=images,
        message=f"Done. This job was: {wait}",
    )

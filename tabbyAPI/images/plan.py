"""LLM dest planner and Comfy prompt rewrite for mixed coding+images."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections import OrderedDict

from common.image_prompts import (
    MAX_PLANNED_IMAGES,
    rewrite_comfy_prompt,
)

LLM_PLAN_TIMEOUT_S = 25
MIXED_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "images": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "subject": {"type": "string"},
                },
                "required": ["filename", "subject"],
            },
        }
    },
    "required": ["images"],
}
EXTRACT_PLAN_SYSTEM = (
    "List every raster PNG the webpage needs. JSON only, no markdown. "
    "Include a logo if they asked for a logo. Include a header if they asked "
    "for a hero/header/banner image. Include one file per named picture "
    "subject (products, places, people, planets, cabins, food, anything they "
    "named). Do not invent a whole category. Skip CSS, HTML, JavaScript, "
    "React, Vue, pricing tiers, and etc. filename is a basename like logo.png "
    "or oak.png, or a project path like pbptours/images/logo.png. "
    "subject is a short photo or logo prompt with no website mockup."
)
_PLAN_CACHE: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
_PLAN_CACHE_MAX = 24
_SKIP_SLUGS = frozenset(
    {"etc", "css", "css3", "html", "html5", "js", "javascript", "react", "vue"}
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_CSS_SLUG_RE = re.compile(
    r"(?is)^("
    r"[\d.-]+(?:px|em|rem|vh|vw|vmin|vmax|pct|deg|turn|fr|s|ms|ch|ex)?"
    r"|auto-fit|auto-fill|minmax|inherit|unset|initial|revert|none|auto"
    r"|linear-gradient|radial-gradient|repeat|rgba?|hsla?"
    r"|var-.+"
    r")$"
)
_SITE_FOLDER_RE = re.compile(
    r"(?is)\b(?:under|in|into|inside)\s+(?:the\s+)?"
    r"(?:folder|directory|dir)\s+[\"`'“”]?([A-Za-z][A-Za-z0-9._-]*)"
)


def _spec_key(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode()).hexdigest()


def remember_plan(text: str, items: list[dict[str, str]]) -> None:
    key = _spec_key(text)
    if key in _PLAN_CACHE:
        _PLAN_CACHE.move_to_end(key)
    _PLAN_CACHE[key] = [dict(row) for row in items]
    while len(_PLAN_CACHE) > _PLAN_CACHE_MAX:
        _PLAN_CACHE.popitem(last=False)


def recalled_plan(text: str) -> list[dict[str, str]]:
    key = _spec_key(text)
    items = _PLAN_CACHE.get(key)
    if not items:
        return []
    _PLAN_CACHE.move_to_end(key)
    return [dict(row) for row in items]


def parse_plan_json(raw: str) -> list[dict[str, str]]:
    text = re.sub(r"(?is)<think>.*?</think>", " ", raw or "")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    blob = fenced.group(1) if fenced else ""
    if not blob:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            blob = text[start : end + 1]
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    rows = data.get("images") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    found: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        filename = str(row.get("filename") or row.get("output_path") or "").strip()
        subject = str(row.get("subject") or row.get("prompt") or "").strip()
        if filename or subject:
            found.append({"filename": filename, "subject": subject})
    return found


def _subject_slug(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug[:40]


def site_images_dir(text: str) -> str:
    match = _SITE_FOLDER_RE.search(text or "")
    folder = (match.group(1) if match else "").strip().strip("/")
    if folder and folder.lower() not in {"images", "image", "v1", "openai"}:
        return f"{folder}/images"
    return "images"


def plan_from_extracted(text: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    dest_dir = site_images_dir(text)
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows or []:
        if len(items) >= MAX_PLANNED_IMAGES:
            break
        filename = str(row.get("filename") or "").replace("\\", "/")
        filename = filename.split("/")[-1].strip()
        slug = _subject_slug(filename.rsplit(".", 1)[0] if filename else "")
        if not slug:
            slug = _subject_slug(str(row.get("subject") or ""))
        if (
            not slug
            or slug in seen
            or slug in _SKIP_SLUGS
            or _CSS_SLUG_RE.match(slug)
        ):
            continue
        name = "logo.png" if slug == "logo" else f"{slug}.png"
        if slug in {"header", "banner", "hero"}:
            name = "header.png"
        subject = str(row.get("subject") or slug).strip() or slug
        seen.add(slug)
        items.append(
            {
                "prompt": rewrite_comfy_prompt(subject),
                "output_path": f"{dest_dir}/{name}".replace("//", "/"),
            }
        )
    return items


def fallback_item(text: str = "") -> list[dict[str, str]]:
    dest_dir = site_images_dir(text)
    return [
        {
            "prompt": rewrite_comfy_prompt("wide photographic scene"),
            "output_path": f"{dest_dir}/generated.png",
        }
    ]


async def llm_plan_images(text: str, disconnect_handler=None) -> list[dict[str, str]]:
    """Ask the loaded coding model for dests. Empty if it cannot run."""
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        from common import model as model_mod
        from endpoints.OAI.types.chat_completion import (
            ChatCompletionMessage,
            ChatCompletionRequest,
        )
        from endpoints.OAI.utils.chat_completion import apply_chat_template
    except Exception:
        return []
    container = getattr(model_mod, "container", None)
    if not container or not getattr(container, "loaded", False):
        return []
    if getattr(container, "prompt_template", None) is None:
        return []
    request = ChatCompletionRequest(
        messages=[
            ChatCompletionMessage(role="system", content=EXTRACT_PLAN_SYSTEM),
            ChatCompletionMessage(role="user", content=raw[:6000]),
        ],
        max_tokens=500,
        temperature=0.1,
        json_schema=MIXED_PLAN_SCHEMA,
    )
    try:
        prompt, embeddings = await apply_chat_template(request)
        result = await asyncio.wait_for(
            container.generate(
                f"mixed-plan-{uuid.uuid4().hex[:12]}",
                prompt,
                request,
                mm_embeddings=embeddings,
                disconnect_handler=disconnect_handler,
            ),
            timeout=LLM_PLAN_TIMEOUT_S,
        )
    except Exception as exc:
        from common.logger import xlogger

        xlogger.warning(f"Mixed dest extract failed: {exc}")
        return []
    blob = ""
    if isinstance(result, dict):
        blob = str(result.get("text") or result.get("content") or "")
    return plan_from_extracted(raw, parse_plan_json(blob))


async def plan_mixed_dests(text: str, disconnect_handler=None) -> list[dict[str, str]]:
    """JSON extract while the LLM is loaded. One generated.png if that fails."""
    raw = text or ""
    items = recalled_plan(raw)
    if items:
        return items
    try:
        items = await llm_plan_images(raw, disconnect_handler=disconnect_handler)
    except Exception:
        items = []
    if not items:
        items = fallback_item(raw)
    remember_plan(raw, items)
    return items

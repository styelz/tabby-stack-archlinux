"""Strip Copilot-style apology openers from chat replies.

VS Code retries failed Write/terminal calls and the coding model then starts
with "I apologize for the repeated errors." We cannot stop that loop inside
the IDE, but we can drop the sentence before the client shows it.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, AsyncIterator, Optional

APOLOGY_SENTENCE = re.compile(
    r"(?is)^\s*"
    r"(?:i(?:'m| am)?\s+sorry|i\s+apologize|apologies(?:\s+for)?|sorry)"
    r"[^.!?\n]{0,220}[.!?]+"
    r"\s*"
)
HOLD_CHARS = 200


def strip_leading_apology(text: str) -> str:
    """Remove leading sorry/apologize sentences. Keep the rest of the reply."""
    cleaned = text or ""
    for _ in range(4):
        nxt = APOLOGY_SENTENCE.sub("", cleaned, count=1)
        if nxt == cleaned:
            break
        cleaned = nxt
    return cleaned


def strip_response_apologies(response):
    """Mutate a ChatCompletionResponse so the IDE does not show the apology."""
    for choice in getattr(response, "choices", None) or []:
        message = getattr(choice, "message", None)
        if message is None:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            message.content = strip_leading_apology(content) or None
    return response


def _choice0(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    return choice if isinstance(choice, dict) else None


def _content_chunk(template: dict[str, Any], text: str) -> str:
    data = copy.deepcopy(template)
    choice = _choice0(data)
    if choice is None:
        return json.dumps(template, ensure_ascii=False)
    choice["delta"] = {"content": text}
    choice["finish_reason"] = None
    choice.pop("eos_reason", None)
    return json.dumps(data, ensure_ascii=False)


def _ready_to_flush(held: str) -> bool:
    if len(held) >= HOLD_CHARS:
        return True
    return bool(re.search(r"[.!?](?:\s|$)", held) or "\n" in held)


async def strip_apology_sse(stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """Hold the first streamed sentence, drop an apology, then pass the rest."""
    held = ""
    template: Optional[dict[str, Any]] = None
    released = False

    def flush() -> Optional[str]:
        nonlocal held, template
        if not held:
            return None
        cleaned = strip_leading_apology(held)
        held = ""
        if not cleaned or template is None:
            return None
        return _content_chunk(template, cleaned)

    async for chunk in stream:
        if released or not isinstance(chunk, str) or chunk == "[DONE]":
            if not released:
                extra = flush()
                released = True
                if extra:
                    yield extra
            yield chunk
            continue
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            extra = flush()
            released = True
            if extra:
                yield extra
            yield chunk
            continue
        if not isinstance(data, dict):
            extra = flush()
            released = True
            if extra:
                yield extra
            yield chunk
            continue
        choice = _choice0(data)
        delta = choice.get("delta") if choice else None
        if not isinstance(delta, dict):
            delta = {}
        content = delta.get("content")
        other = bool(
            delta.get("tool_calls")
            or delta.get("reasoning_content")
            or (choice or {}).get("finish_reason")
        )
        if isinstance(content, str) and content and not other:
            held += content
            template = data
            if _ready_to_flush(held):
                extra = flush()
                released = True
                if extra:
                    yield extra
            continue
        extra = flush()
        released = True
        if extra:
            yield extra
        yield chunk

    if not released:
        extra = flush()
        if extra:
            yield extra

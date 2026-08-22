"""Detect Cursor chat phrases for listing and switching TabbyAPI models."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from ruamel.yaml import YAML
from sse_starlette import EventSourceResponse

from common.gpu_mode import (
    GPU_ALIASES,
    public_api_base,
    public_image_url,
    read_mode,
    recent_generated_files,
)
from common.logger import xlogger
from common.networking import get_sse_ping_interval
from common.pasted_images import is_save_image_request, pasted_download_text
from common.switch_times import (
    extra_seconds,
    format_duration,
    gpu_label,
    profile_error,
    ready_seconds,
    wait_hint,
)
from endpoints.OAI.types.chat_completion import (
    ChatCompletionMessage,
    ChatCompletionMessagePart,
    ChatCompletionRequest,
    ChatCompletionRespChoice,
    ChatCompletionResponse,
    ChatCompletionStreamChoice,
    ChatCompletionStreamChunk,
)
from endpoints.OAI.types.tools import Tool, ToolCall

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
PROFILES_DIR = ROOT / "model_profiles"
PYTHON = (
    ROOT
    / "venv"
    / ("Scripts" if os.name == "nt" else "bin")
    / ("python.exe" if os.name == "nt" else "python")
)
SWITCHER = ROOT / "switch_model.py"
RESTARTER = ROOT / "restart_stack.py"
LOG = ROOT / "switch-model.log"
LOCK = ROOT / "switch-model.lock"

SWITCH_RE = re.compile(
    r"(?is)^\s*(?:please\s+)?(?:switch(?:\s+to)?|use)\s+(\S+)(?:\s+now)?[\s!.]*$"
)
LIST_RE = re.compile(r"(?is)^\s*(?:please\s+)?(?:list|show|available)\s+models?[\s!.]*$")
HELP_RE = re.compile(r"(?is)^\s*(?:please\s+)?help(?:\s+please)?[\s!.?]*$")
RESTART_RE = re.compile(
    r"(?is)^\s*(?:please\s+)?"
    r"restart(?:\s+(?:the\s+)?(?:stack|api|tabby(?:api)?|server|service))?"
    r"(?:\s+now)?[\s!.]*$"
)
IMAGE_GEN_RE = re.compile(
    r"(?is)^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
    r"(?:generate|draw|imagine|create|make|render)"
    r"(?:\s+me)?(?:\s+an?)?(?:\s+image|picture|photo|pic)?"
    r"(?:\s+of|\s+showing)?\s+(.+?)\s*$"
)
IMAGE_COUNT_RE = re.compile(
    r"(?is)^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
    r"(?:generate|draw|imagine|create|make|render|give\s+me)?"
    r"\s*(?P<num>\d+|two|three|four|five)"
    r"\s+(?:different\s+)?(?:images?|pictures?|photos?|pics?)"
    r"(?:\s+of|\s+showing)?\s*(?P<rest>.*)$"
)
_IMAGE_COUNT_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}
MAX_CHAT_IMAGES = 5
# After unwrap, a real image prompt can be a few thousand chars (Qwen-Image
# posters/UI). Agent dumps are typically 10k+. Keep a cap as a backstop.
MAX_IMAGE_PROMPT_CHARS = 4000
META_IMAGE_RE = re.compile(
    r"(?is)\b("
    r"when i asked|it worked|not what i asked|stuck in a loop|"
    r"showed a preview|over and over|the image is not"
    r")\b"
)
# IDEs (GitHub Copilot, Cursor, ...) send a separate, low-stakes completion
# asking the model to name the conversation/PR, and they typically echo the
# user's own request verbatim inside it. "delete the current logo.png and
# create a new logo png image..." inside that wrapper matches IMAGE_REDO_RE
# just as well as the real ask, so a title request must not be treated as a
# fresh image/redo turn — that queued a second, unwanted Comfy render on top
# of the real one (two items, one job) and briefly wedged the mixed-image
# helpers, since none of them expect the "last user message" to be a title
# prompt rather than the user's actual line.
META_WRAPPER_RE = re.compile(
    r"(?is)^\s*(?:please\s+)?"
    r"(?:write|generate|give|suggest|create)\s+(?:me\s+)?(?:a\s+)?"
    r"(?:brief|short|concise|one[- ]word|few[- ]word|catchy)?\s*"
    r"(?:title|summary|name)\s+for\s+(?:the\s+|this\s+)?(?:following\s+)?"
    r"(?:request|conversation|chat|task|message|prompt)?"
    r"|^\s*(?:please\s+)?summariz\w*\s+(?:the\s+)?(?:following|this)\b"
)


def _is_meta_wrapper_text(text: str) -> bool:
    """True for an IDE's own title/summary request, not a user ask."""
    return bool(text) and bool(META_WRAPPER_RE.match(text.strip()))
AGENT_MARKERS = (
    "<user_query>",
    "<userRequest>",
    "You are Cursor",
    "You are an AI coding assistant",
    "PRIORITY: refuse",
    "Available Tools",
)
COMFY_IDLE = (
    "GPU is on ComfyUI. Describe the image in this chat "
    "(for example: a red bicycle in the rain). "
    "The reply will include a PNG URL on this same API host. "
    "Send switch to qwen when you want the LLM back."
)


def llm_not_ready_text() -> str:
    qwen = wait_hint("qwen").lower()
    qwen35 = format_duration(ready_seconds("qwen35"))
    return (
        "No LLM is loaded. This is not an image request and ComfyUI is not involved. "
        f"Send switch to qwen and {qwen} "
        f"(qwen35 can take about {qwen35} on {gpu_label()}). "
        "Send switch to comfy only if you want Flux images."
    )


def llm_loading_text(name: str = "") -> str:
    key = (name or "").strip().lower() or "qwen"
    if key == "restart":
        return restart_reply_text()
    if key in GPU_ALIASES or key == "comfy":
        return comfy_starting_text()
    hint = wait_hint(key)
    extra = ""
    if key in ("qwen35", "qwen36"):
        extra = f" ({key} on {gpu_label()})"
    return f"A model is still loading. {hint}{extra}, then keep using gpt-4o."


def comfy_starting_text() -> str:
    return (
        f"ComfyUI is still starting. {wait_hint('comfy')}, then send a short "
        "image description (for example: a red bicycle in the rain)."
    )


def comfy_not_running_text() -> str:
    return (
        "ComfyUI is not running. Send switch to comfy, "
        f"{wait_hint('comfy').lower()}, then try again."
    )
# Cursor uses <user_query>; VS Code Copilot/custom-endpoint uses <userRequest>.
QUERY_TAG_RE = re.compile(
    r"<(user_query|userRequest|UserRequest|userPrompt|user_prompt)>\s*(.*?)\s*</\1>",
    re.S | re.I,
)
SAVE_IMAGE_RE = re.compile(
    r"(?is)\b(save|write|export|download)\b.*\b(image|screenshot|png|jpe?g|photo|picture)\b"
    r"|\b(image|screenshot|png|jpe?g|photo|picture)\b.*\b(save|write|export|download)\b"
)
CLIPBOARD_HINT_MARK = "The pasted image lives on the TabbyAPI host, not this workspace."


def clipboard_save_hint(api_base: Optional[str] = None) -> str:
    """Point a remote client at the paste URL on this API."""
    base = (api_base or public_api_base()).rstrip("/")
    url = f"{base}/images/pasted/latest.png"
    return (
        f"{CLIPBOARD_HINT_MARK} "
        "It is at this API URL (same host as this chat):\n"
        f"{url}"
    )


# Older tests / callers
CLIPBOARD_HINT = clipboard_save_hint()


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


def last_user_raw(data: ChatCompletionRequest) -> str:
    for message in reversed(data.messages or []):
        if message.role != "user":
            continue
        return _content_text(message.content)
    return ""


def _unwrap_query(text: str) -> str:
    matches = list(QUERY_TAG_RE.finditer(text))
    if matches:
        return matches[-1].group(2).strip()
    return text.strip()


def last_user_text(data: ChatCompletionRequest) -> str:
    return _unwrap_query(last_user_raw(data))


def _command_candidates(data: ChatCompletionRequest) -> list[str]:
    """Possible user-typed commands, including VS Code/Cursor wrappers.

    Agent prompts include workspace rules like ``switch to qwen35``. Only scan
    the tagged user line for those, never the whole system prompt.
    """
    raw = last_user_raw(data)
    unwrapped = _unwrap_query(raw)
    seen: set[str] = set()
    out: list[str] = []

    def add(candidate: str) -> None:
        candidate = candidate.strip().strip("`")
        if candidate and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)

    add(unwrapped)
    if any(marker.lower() in raw.lower() for marker in AGENT_MARKERS):
        for line in unwrapped.splitlines():
            add(line)
        return out
    add(raw)
    for line in raw.splitlines():
        add(line)
    return out


def _match_any(pattern: re.Pattern, data: ChatCompletionRequest):
    for candidate in _command_candidates(data):
        match = pattern.match(candidate)
        if match:
            return match
    return None


def _load_yaml(path: Path):
    yaml = YAML(typ="safe")
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle) or {}


def profile_map() -> dict[str, dict]:
    """alias / folder name -> {alias, folder, pretty} from model_profiles/*.yml"""
    mapping = {}
    if not PROFILES_DIR.exists():
        return mapping
    for path in PROFILES_DIR.glob("*.yml"):
        data = _load_yaml(path)
        alias = path.stem.lower()
        model_cfg = data.get("model") or {}
        folder = model_cfg.get("model_name")
        pretty = data.get("pretty") or folder or alias
        entry = {
            "alias": alias,
            "folder": folder,
            "pretty": pretty,
            "max_seq_len": model_cfg.get("max_seq_len"),
            "cache_size": model_cfg.get("cache_size"),
            "vision": bool(model_cfg.get("vision")),
        }
        mapping[alias] = entry
        if folder:
            mapping[folder.lower()] = entry
    return mapping


def installed_models() -> list[str]:
    """Folder names under models/ that look like real EXL3 downloads."""
    if not MODELS_DIR.exists():
        return []
    names = []
    for path in sorted(MODELS_DIR.iterdir(), key=lambda p: p.name.lower()):
        if path.is_dir() and (path / "config.json").exists():
            names.append(path.name)
    return names


def current_folder() -> Optional[str]:
    try:
        from common import model as model_mod

        if model_mod.container and getattr(model_mod.container, "model_dir", None):
            return model_mod.container.model_dir.name
    except Exception:
        return None
    return None


def resolve_switch_target(token: str) -> Optional[str]:
    """Return a switch_model.py profile alias, or None if unknown."""
    key = token.strip().lower()
    if key in GPU_ALIASES or key == "llm":
        return GPU_ALIASES.get(key, "llm")
    profiles = profile_map()
    if key in profiles:
        return profiles[key]["alias"]
    return None


def requested_profile(data: ChatCompletionRequest) -> Optional[str]:
    match = _match_any(SWITCH_RE, data)
    if not match:
        return None
    return resolve_switch_target(match.group(1))


def is_list_request(data: ChatCompletionRequest) -> bool:
    return bool(_match_any(LIST_RE, data))


def is_help_request(data: ChatCompletionRequest) -> bool:
    return bool(_match_any(HELP_RE, data))


def is_restart_request(data: ChatCompletionRequest) -> bool:
    return bool(_match_any(RESTART_RE, data))


def _ctx_label(entry: dict) -> str:
    raw = entry.get("max_seq_len") or entry.get("cache_size")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return ""
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


def _is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def help_api_urls(
    api_base: Optional[str] = None, request=None
) -> tuple[str, str]:
    """Client-facing (base, origin). Empty when only a loopback URL is known."""
    base = (api_base or public_api_base(request) or "").rstrip("/")
    if not base or _is_loopback_url(base):
        return "", ""
    origin = base[:-3] if base.endswith("/v1") else base
    return base, origin


def help_text(api_base: Optional[str] = None, request=None) -> str:
    """Full usage guide for a chat line that is only ``help``."""
    profiles = profile_map()
    loaded = current_folder()
    aliases = []
    seen = set()
    for path in sorted(PROFILES_DIR.glob("*.yml")) if PROFILES_DIR.exists() else []:
        alias = path.stem.lower()
        if alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)

    base, origin = help_api_urls(api_base, request)
    if base:
        api_lines = [
            f"This API (as configured on this server): {base}",
            "Talk to it over HTTP like OpenAI. Model name: gpt-4o (leave it).",
        ]
        if origin:
            api_lines.append(f"Health: GET {origin}/health")
        embed = f"POST {base}/embeddings"
    else:
        api_lines = [
            "This API uses the /v1 URL configured in your IDE (external host or proxy).",
            "Talk to it over HTTP like OpenAI. Model name: gpt-4o (leave it).",
        ]
        embed = "POST /v1/embeddings"

    lines = [
        "Use gpt-4o as the model name in your editor, and leave it. "
        "That is not ChatGPT — it is only a name. Many editors sandbox or block tools "
        "unless they see a known OpenAI name. The GPU still runs the local model you switched to.",
        "",
        "This is a TabbyAPI + ComfyUI stack on one NVIDIA GPU.",
        "The coding workspace is a different computer from the GPU server.",
        *api_lines,
        "",
        "The GPU is exclusive: LLM or Comfy, never both.",
        f"Qwen3-Embedding-0.6B stays on CPU ({embed}). No switch needed for search.",
        "",
        "Send a message that is only one of these phrases:",
        "",
        "  help                 this guide",
        "  list models          installed profiles and which is loaded",
        "  restart              bounce the API; last model reloads",
        "  switch to qwen       daily coding (9B, vision)",
        "  switch to qwen35     long / hard agent work",
        "  switch to qwen36     long / hard agent work",
        "  switch to gemma      general",
        "  switch to gemma26    stronger general",
        f"  switch to glm        thinking (vision is off on {gpu_label()})"
        if not (profiles.get("glm") or {}).get("vision", True)
        else "  switch to glm        thinking / vision",
        "  switch to comfy      unload the LLM; Flux / Qwen-Image",
        "  switch to flux       same as comfy",
        "  switch to llm        free Comfy; reload the last LLM",
        "",
        f"Wait times are warm switches on this {gpu_label()} (first boot can compile Triton longer):",
    ]
    for alias in aliases:
        entry = profiles.get(alias) or {}
        pretty = entry.get("pretty") or alias
        ctx = _ctx_label(entry)
        wait = format_duration(ready_seconds(alias))
        mark = "  [loaded]" if entry.get("folder") == loaded else ""
        ctx_bit = f", {ctx} ctx" if ctx else ""
        lines.append(f"  {alias}: {pretty}{ctx_bit} — about {wait}{mark}")
    flux = extra_seconds("comfy", "flux_s")
    qwen_img = extra_seconds("comfy", "qwen_image_s")
    comfy_ready = format_duration(ready_seconds("comfy"))
    llm_ready = format_duration(ready_seconds("llm"))
    lines.append(f"  comfy: process ready in about {comfy_ready}")
    if flux:
        lines.append(f"  first Flux draft: about {format_duration(flux)}")
    if qwen_img:
        lines.append(f"  first Qwen-Image (text / UI): about {format_duration(qwen_img)}")
    lines.append(f"  switch to llm: about {llm_ready}")
    images_post = f"POST {base}/images/generations" if base else "POST /v1/images/generations"
    images_get = f"GET {base}/images/latest.png" if base else "GET /v1/images/latest.png"
    lines.extend(
        [
            "",
            "Examples",
            "  Chat (send as the whole message):",
            "    help",
            "    list models",
            "    restart",
            "    switch to qwen",
            "    generate an image of a red bicycle",
            "    qwen-image: a poster with the heading SALE",
            "",
            "  Images (OpenAI-shaped):",
            f"    {images_post}",
            '    {"prompt": "qwen-image: login form with Submit"}',
            f"    {images_get}",
            "",
            "Images (any IDE):",
            "  1. Send switch to comfy and wait until Comfy is ready, then describe the image.",
            "  2. Or one line: generate an image of a red bicycle",
            "     (API hands the GPU to Comfy, returns a URL, reloads the last LLM).",
            "  3. Flux Schnell is the default draft backend.",
            "  4. Readable text / posters / UI: prefix qwen-image: or mention poster, button, logo. "
            "Hero/header photos are Flux — describe a scene, not a website.",
            "  5. Paste a photo in the same turn for Flux img2img.",
            "  6. The reply includes a PNG URL on this same API host. The markdown preview is the picture.",
            f"  7. Or {images_post} (returns b64_json + url). Works in every editor.",
            "  8. Send switch to qwen when you want the coding model back.",
            "",
            "Coding plus images (same chat, any IDE):",
            "  The API starts the PNG job from the user line. "
            "Do not use generate_image and do not POST /v1/mcp for that batch.",
            "  Keep using the wait or download tool this API requests until the PNGs exist.",
            "  Then use Write or StrReplace for HTML/CSS/JS. A chat dump is not a file.",
            "  Do not fake images with SVG, CSS art, Pillow/PIL, emoji, placeholder URLs, or Unsplash.",
            "  Point img src at the planned local PNG paths. Never use the browser.",
            f"  Flux draft: about {format_duration(flux) if flux else 'a few minutes'} each. "
            f"Qwen-Image (text / UI / logo): about {format_duration(qwen_img) if qwen_img else 'a few minutes'} each. "
            f"The coding model reloads once at the end (about {llm_ready}).",
            "  Write/StrReplace cannot save PNG bytes.",
            "",
            "Daily work: stay on qwen. For a long agent job, switch to qwen35 or qwen36 first,",
            "then continue in a new chat. Split big work: explore, stop, then a second chat that only edits.",
            "",
            "Send list models for the short profile list.",
        ]
    )
    return "\n".join(lines)


def list_text() -> str:
    profiles = profile_map()
    loaded = current_folder()
    lines = [
        "Stay on gpt-4o. To switch, type switch to <model>. "
        "Send restart to bounce the API. Send help for the full guide.",
        "Daily chat: qwen. Long Agent tasks: switch to qwen35 or qwen36 first.",
        "Image gen: switch to comfy (unloads the LLM, Flux Schnell). "
        "Switch back with switch to qwen.",
        "",
    ]
    found = False
    for folder in installed_models():
        found = True
        entry = profiles.get(folder.lower())
        if entry:
            ctx = entry.get("max_seq_len") or entry.get("cache_size")
            bits = []
            if folder == loaded:
                bits.append("loaded")
            if ctx:
                bits.append(f"{ctx} ctx")
            extra = f" ({', '.join(bits)})" if bits else ""
            lines.append(f"- {entry['pretty']}{extra} | switch to {entry['alias']}")
        else:
            extra = " (loaded)" if folder == loaded else ""
            lines.append(f"- {folder}{extra} | switch to {folder}")
    if not found:
        lines.append("No models installed.")
    lines.append("- Flux Schnell (ComfyUI) | switch to comfy")
    return "\n".join(lines)


def restart_wait_name() -> str:
    if gpu_is_comfy():
        return "comfy"
    try:
        from select_model import last_profile

        name = last_profile()
    except Exception:
        name = None
    return name or "qwen"


def restart_reply_text() -> str:
    name = restart_wait_name()
    hint = wait_hint(name)
    if name == "comfy":
        return (
            f"Restarting the stack. {hint}, then describe an image "
            "or send switch to qwen."
        )
    return f"Restarting the stack. {hint}, then keep using gpt-4o."


def start_restart() -> bool:
    """Detach a delayed systemd bounce so this chat reply can flush."""
    if shutil.which("systemctl") is None:
        return False
    LOG.touch(exist_ok=True)
    LOCK.write_text("restart", encoding="utf-8")
    mode = "comfy" if gpu_is_comfy() else "llm"
    with LOG.open("a", encoding="utf-8") as log:
        log.write("\n--- restart (from chat) ---\n")
        log.flush()
        kwargs: dict = {
            "cwd": str(ROOT),
            "stdout": log,
            "stderr": log,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000 | 0x00000008
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(
                [
                    str(PYTHON),
                    str(RESTARTER),
                    "--delay",
                    "1.5",
                    "--mode",
                    mode,
                    "--lock",
                    str(LOCK),
                ],
                **kwargs,
            )
        except OSError:
            LOCK.unlink(missing_ok=True)
            return False
    xlogger.info("Phrase restart started")
    return True


def start_switch(name: str) -> None:
    LOG.touch(exist_ok=True)
    # Write the lock before spawning: switch_model.py removes it when it exits,
    # and a fast failure (unknown profile, server down) would otherwise finish
    # first and leave a lock nobody clears for 180s.
    LOCK.write_text(name, encoding="utf-8")
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n--- switch {name} (from Cursor chat) ---\n")
        log.flush()
        kwargs: dict = {
            "cwd": str(ROOT),
            "stdout": log,
            "stderr": log,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen([str(PYTHON), str(SWITCHER), name], **kwargs)
        except OSError:
            LOCK.unlink(missing_ok=True)
            raise
    xlogger.info(f"Phrase switch started: {name}")


def switch_reply_text(name: str) -> str:
    hint = wait_hint(name)
    if name == "comfy":
        return (
            f"Switching the GPU to ComfyUI / Flux. {hint}. "
            "TabbyAPI stays up; the LLM is unloaded. "
            "Next message: a short image description, or POST /v1/images/generations. "
            "The reply includes a download URL on this API host. "
            "Send switch to qwen when you want the LLM back."
        )
    if name == "llm":
        return (
            "Freeing ComfyUI and reloading the last TabbyAPI model. "
            f"{hint}, then keep using gpt-4o."
        )
    entry = profile_map().get(name, {})
    pretty = entry.get("pretty") or name
    err = profile_error(name)
    extra = ""
    if err:
        extra = (
            f" On {gpu_label()} this profile previously failed ({err}). "
            "If the load fails, switch to qwen."
        )
    return (
        f"Switching TabbyAPI to {pretty} (ComfyUI weights will be unloaded). "
        f"{hint}, then keep using gpt-4o. "
        f"The next message will use the new model.{extra}"
    )


def text_response(data: ChatCompletionRequest, text: str):
    if data.stream:
        return EventSourceResponse(
            stream_text(data, text),
            ping=get_sse_ping_interval(),
            sep="\n",
        )
    return ChatCompletionResponse(
        model=data.model or "gpt-4o",
        choices=[
            ChatCompletionRespChoice(
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=text),
            )
        ],
    )


def tool_call_response(
    data: ChatCompletionRequest,
    calls: list[tuple[str, dict]],
    *,
    content: Optional[str] = None,
):
    """Drive Cursor tools while the coding model is off the GPU."""
    tool_calls = [
        ToolCall(
            function=Tool(name=name, arguments=json.dumps(arguments, ensure_ascii=False)),
            type="function",
            index=index,
        )
        for index, (name, arguments) in enumerate(calls)
    ]
    message = ChatCompletionMessage(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
    )
    if data.stream:
        return EventSourceResponse(
            stream_tool_calls(data, message),
            ping=get_sse_ping_interval(),
            sep="\n",
        )
    return ChatCompletionResponse(
        model=data.model or "gpt-4o",
        choices=[
            ChatCompletionRespChoice(
                finish_reason="tool_calls",
                message=message,
            )
        ],
    )


async def stream_text(data: ChatCompletionRequest, text: str):
    chunk_id = f"chatcmpl-{uuid4().hex}"
    model_name = data.model or "gpt-4o"
    first = ChatCompletionStreamChunk(
        id=chunk_id,
        model=model_name,
        choices=[
            ChatCompletionStreamChoice(delta=ChatCompletionMessage(role="assistant", content=text))
        ],
    )
    last = ChatCompletionStreamChunk(
        id=chunk_id,
        model=model_name,
        choices=[ChatCompletionStreamChoice(delta={}, finish_reason="stop")],
    )
    yield first.model_dump_json()
    yield last.model_dump_json()


async def stream_tool_calls(data: ChatCompletionRequest, message: ChatCompletionMessage):
    """OpenAI-shaped SSE deltas. Cursor ignores a whole ChatCompletionMessage dump."""
    chunk_id = f"chatcmpl-{uuid4().hex}"
    model_name = data.model or "gpt-4o"
    created = int(time.time())

    def dump(delta: dict, finish: Optional[str] = None) -> str:
        return json.dumps(
            {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish,
                    }
                ],
            },
            ensure_ascii=False,
        )

    yield dump({"role": "assistant"})
    tool_payload = []
    for index, call in enumerate(message.tool_calls or []):
        item = call.model_dump(mode="json", exclude_none=True)
        item["index"] = index
        tool_payload.append(item)
    if tool_payload:
        yield dump({"tool_calls": tool_payload})
    yield dump({}, finish="tool_calls")


def inject_clipboard_save_hint(
    data: ChatCompletionRequest, api_base: Optional[str] = None
) -> None:
    """Tell the model to download the paste from this API when the user asked to save."""
    if not SAVE_IMAGE_RE.search(last_user_text(data)):
        return
    hint = clipboard_save_hint(api_base)
    for message in reversed(data.messages or []):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            if CLIPBOARD_HINT_MARK in content:
                return
            message.content = content + "\n" + hint
            return
        if isinstance(content, list):
            for part in content:
                if CLIPBOARD_HINT_MARK in (getattr(part, "text", None) or ""):
                    return
            message.content = list(content) + [
                ChatCompletionMessagePart(type="text", text=hint)
            ]
        return


def last_role(data: ChatCompletionRequest) -> str:
    messages = data.messages or []
    if not messages:
        return ""
    return (messages[-1].role or "").lower()


def already_made_image(data: ChatCompletionRequest) -> bool:
    """True after we already generated or asked Cursor to save this turn."""
    for message in data.messages or []:
        if message.role == "assistant":
            content = _content_text(message.content)
            if "Image is ready" in content or "/images/generated-" in content:
                return True
            for call in message.tool_calls or []:
                args = getattr(getattr(call, "function", None), "arguments", "") or ""
                if "generated-latest.png" in args or "generated.png" in args:
                    return True
        if message.role in ("tool", "function"):
            content = _content_text(message.content)
            if "generated.png" in content or "generated-latest" in content:
                return True
    return False


def has_new_user_after_image(data: ChatCompletionRequest) -> bool:
    """True when the user sent a new line after the last generated preview."""
    last_image = -1
    last_user = -1
    for index, message in enumerate(data.messages or []):
        content = _content_text(message.content)
        if message.role == "assistant" and (
            "Image is ready" in content or "/images/generated-" in content
        ):
            last_image = index
        if message.role == "user":
            last_user = index
    return last_user > last_image


IMAGE_NOUN_RE = re.compile(
    r"(?is)\b(image|picture|photo|pic|poster|mockup|icon|logo|banner|qwen-image)\b"
)
CODING_TASK_RE = re.compile(
    r"(?is)\b("
    r"web\s*page|website|web\s*site|html|css|javascript|typescript|"
    r"homepage|landing\s*page|component|implement|source\s*code|"
    r"react|vue|jsx|tsx"
    r")\b"
)
# Follow-up after a webpage+images ask: "now create the page", "don't use SVGs".
MIXED_FOLLOWUP_RE = re.compile(
    r"(?is)("
    r"\b(?:create|write|make|build|save|put)\b.{0,100}"
    r"\b(?:page|html|css|files?|website|web\s*site|project|workspace)\b"
    r"|"
    r"\b(?:page|html|website|web\s*site|files?)\b.{0,100}"
    r"\b(?:create|write|make|build|save)\b"
    r"|"
    r"\b(?:svgs?|placeholders?|stock (?:photo|image)|unsplash)\b"
    r"|"
    r"\b(?:real|actual|generated)\s+(?:pngs?|images?|photos?)\b"
    r"|"
    r"\b(?:png|raster)\s+(?:images?|files?|photos?)\b"
    r"|"
    r"\bdo as i (?:ask|say|told you)\b"
    r"|"
    r"\brewrite\s+(?:this\s+)?prompt\b"
    r"|"
    r"\binstead of\s+svgs?\b"
    r"|"
    r"\bnot\s+(?:an?\s+)?svgs?\b"
    r")"
)
MIXED_IMAGE_HINT_MARK = "This turn is a coding task that also needs images."
FAKE_IMAGE_SCRIPT_RE = re.compile(
    r"(?is)("
    r"generate_images\.py|"
    r"make_images\.py|"
    r"create_(?:the_)?images\.py|"
    r"from\s+PIL(?:\s+import|\s*\.)|"
    r"import\s+PIL\b|"
    r"\bImageDraw\b|"
    r"\bImageFont\b|"
    r"PIL\.Image|"
    r"\bsvgwrite\b|"
    r"\bcairosvg\b|"
    r"\bsvg2png\b|"
    r"Image\.new\s*\("
    r")"
)
FAKE_PNG_NOTE = (
    "Those PNG files must come from the GPU job, not from Pillow, SVG, "
    "or a Python drawing script. Do not write or run generate_images.py. "
    "Do not overwrite the planned .png paths with local drawings. "
    "Downloading the real GPU PNGs again. After they land, write HTML/CSS/JS only."
)
IMAGE_DOWNLOAD_STOP_NOTE = (
    "The GPU PNG download failed (HTTP 404 or the file is gone from this host). "
    "Do not keep curling that URL. Do not write generate_images.py or Pillow "
    "stand-ins. Wait for a new image job, then curl only URLs this API invents."
)
IMAGE_DOWNLOAD_UNCONFIRMED_NOTE = (
    "The GPU still has these PNGs. The coding client never confirmed they "
    "landed on disk (no ls listing, or curl failed through the tunnel). "
    "Do not write generate_images.py or Pillow stand-ins. "
    "Save them with Shell curl of only these URLs, then write HTML/CSS/JS."
)
IMAGE_REDO_RE = re.compile(
    r"(?is)("
    r"\b(?:improve|better|regenerat\w*|re-?generat\w*|redo|re-?do|"
    r"re-?creat\w*|replac\w*)\b.{0,80}"
    r"\b(?:logo|header|banner)(?:\s+image|\.png)?\b"
    r"|"
    r"\b(?:logo|header|banner)(?:\s+image|\.png)?\b.{0,80}"
    r"\b(?:improve|better|regenerat\w*|re-?creat\w*|replac\w*)\b"
    r"|"
    r"\b(?:delete|remove|rm)\b.{0,100}\b(?:logo|header).{0,80}"
    r"\b(?:creat|generat|mak|draw|new)\b"
    r"|"
    r"\b(?:generat|creat|mak|draw|render)\w*\s+"
    r"(?:me\s+)?(?:the\s+|a\s+new\s+|an?\s+improved\s+)"
    r"(?:logo|header)(?:\s+image|\.png)?"
    r"|"
    r"\buse\s+flux\b.{0,60}\b(?:logo|header|generat|creat)\w*"
    r"|"
    r"\b(?:the\s+)?(?:logo|header)(?:\s+image)?\s+should\s+be\b"
    r")"
)


def is_coding_task(text: str) -> bool:
    return bool(CODING_TASK_RE.search(text or ""))


def _queries_in(text: str) -> list[str]:
    matches = list(QUERY_TAG_RE.finditer(text or ""))
    if matches:
        return [m.group(2).strip() for m in matches if m.group(2).strip()]
    stripped = (text or "").strip()
    return [stripped] if stripped else []


def _text_is_mixed_image(text: str) -> bool:
    return bool(text) and is_coding_task(text) and bool(IMAGE_NOUN_RE.search(text))


def _text_is_image_redo(text: str) -> bool:
    """True when the user wants one existing PNG replaced, not the whole site."""
    return bool(text) and bool(IMAGE_REDO_RE.search(text))


def _last_ask_text(data: ChatCompletionRequest) -> str:
    raw = last_user_raw(data)
    text = _unwrap_query(raw) or last_user_text(data)
    if MIXED_IMAGE_HINT_MARK in text:
        text = text.split(MIXED_IMAGE_HINT_MARK, 1)[0]
    text = (text or "").strip()
    if _is_meta_wrapper_text(text):
        return ""
    return text


def conversation_asked_for_page_images(data: ChatCompletionRequest) -> bool:
    """True if this chat already asked for a page plus generated images."""
    for message in data.messages or []:
        if message.role != "user":
            continue
        raw = _content_text(message.content)
        if MIXED_IMAGE_HINT_MARK in raw:
            return True
        for query in _queries_in(raw):
            if _text_is_mixed_image(query):
                return True
    return False


def is_mixed_image_request(data: ChatCompletionRequest) -> bool:
    text = last_user_text(data)
    if _is_meta_wrapper_text(text):
        return False
    if _text_is_mixed_image(text) or _text_is_image_redo(_last_ask_text(data)):
        return True
    if not text or not conversation_asked_for_page_images(data):
        return False
    return bool(is_coding_task(text) or MIXED_FOLLOWUP_RE.search(text))


def _render_seconds(prompt: str = "") -> int:
    from common.gpu_mode import wants_qwen_image

    qwen = wants_qwen_image(prompt) if prompt else False
    render = extra_seconds("comfy", "qwen_image_s" if qwen else "flux_s")
    if render is None:
        return 240 if qwen else 180
    return int(render)


def _prompt_list(
    prompt: str = "", count: int = 1, prompts: Optional[list[str]] = None
) -> list[str]:
    if prompts:
        return [str(item or "").strip() or "image" for item in prompts] or ["image"]
    return [prompt or ""] * max(1, int(count))


def image_job_wait_text(
    prompt: str = "",
    restore: bool = True,
    count: int = 1,
    prompts: Optional[list[str]] = None,
) -> str:
    """Measured wait for one Comfy batch, from switch_times.json."""
    from common.gpu_mode import wants_qwen_image

    texts = _prompt_list(prompt, count, prompts)
    n = len(texts)
    llm_s = format_duration(ready_seconds("llm"))
    if n == 1:
        qwen = wants_qwen_image(texts[0]) if texts[0] else False
        backend = "Qwen-Image" if qwen else "Flux"
        render_s = format_duration(_render_seconds(texts[0]))
        bits = [f"about {render_s} to render ({backend})"]
        if restore:
            bits.append(f"about {llm_s} to reload the coding model")
        one = ", then ".join(bits)
        return one[0].upper() + one[1:] + "."

    total_render = sum(_render_seconds(text) for text in texts)
    bits = [
        f"{n} images in one Comfy session",
        f"about {format_duration(total_render)} to render",
    ]
    if restore:
        bits.append(f"about {llm_s} to reload the coding model once at the end")
    return ", ".join(bits) + ". Keep calling tools; Shell writes the PNGs this turn."


def image_job_wait_seconds(
    prompt: str = "",
    restore: bool = True,
    count: int = 1,
    prompts: Optional[list[str]] = None,
) -> int:
    """Estimated seconds for a Comfy batch (handoff + renders + optional LLM reload)."""
    from endpoints.core.image_jobs import MCP_HANDOFF_DELAY_S

    texts = _prompt_list(prompt, count, prompts)
    total = int(MCP_HANDOFF_DELAY_S)
    for text in texts:
        total += _render_seconds(text)
    if restore:
        total += ready_seconds("llm")
    return max(30, total)


SHELL_TOOL_NAMES = (
    "shell",
    "run_terminal_cmd",
    "run_in_terminal",
    "bash",
    "terminal",
    "execute_command",
    "run_command",
    "run_terminal_command",
)
IMAGE_POLL_TOOL_NAMES = ("get_image_job",)
IMAGE_DOWNLOAD_MAX_ATTEMPTS = 4


def _spec_tool_name(spec) -> str:
    if spec is None:
        return ""
    if isinstance(spec, str):
        return spec.strip()
    func = getattr(spec, "function", None)
    name = getattr(func, "name", None) if func is not None else None
    if name:
        return str(name)
    if isinstance(spec, dict):
        nested = spec.get("function")
        if isinstance(nested, dict) and nested.get("name"):
            return str(nested["name"])
        if spec.get("name"):
            return str(spec["name"])
    name = getattr(spec, "name", None)
    return str(name) if name else ""


def _request_tool_names(data: ChatCompletionRequest) -> list[str]:
    """Tools this client can actually run.

    Use the OpenAI tools/functions arrays, plus names that already have a
    tool-role result in this chat. Do not invent get_image_job from an
    assistant call we injected earlier — Cursor Cloud then fails that tool
    and POSTs /v1/chat/completions every second.
    """
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        text = str(name or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        names.append(text)

    for spec in data.tools or []:
        add(_spec_tool_name(spec))
    for spec in data.functions or []:
        add(_spec_tool_name(spec))

    messages = list(data.messages or [])
    for index, message in enumerate(messages):
        if message.role != "assistant":
            continue
        called: list[str] = []
        for call in message.tool_calls or []:
            called.append(_tool_name_of(call))
        for match in re.finditer(
            r"<function=([^>\s]+)", _content_text(message.content) or ""
        ):
            called.append(match.group(1))
        if (
            called
            and index + 1 < len(messages)
            and messages[index + 1].role in ("tool", "function")
        ):
            for name in called:
                add(name)
    return names


def _tool_name_of(call) -> str:
    func = getattr(call, "function", None)
    return str(getattr(func, "name", None) or "")


def chat_is_waiting_on_images(data: ChatCompletionRequest) -> bool:
    """True when this turn is still the webpage+images job, not a new user line.

    A brand-new mixed user message (no tools yet) is not waiting — that used
    to let a leftover done job invent curl instead of starting Comfy.
    """
    if last_role(data) in ("tool", "function"):
        return True
    for message in reversed(data.messages or []):
        if message.role == "assistant" and message.tool_calls:
            for call in message.tool_calls:
                name = _tool_name_of(call).lower()
                if (
                    "get_image_job" in name
                    or "generate_image" in name
                    or name in SHELL_TOOL_NAMES
                ):
                    return True
            return False
        if message.role == "user":
            break
    return False


def _history_has_image_tools(data: ChatCompletionRequest) -> bool:
    """True if this chat already called generate_image / get_image_job."""
    for message in data.messages or []:
        if message.role != "assistant":
            continue
        for call in message.tool_calls or []:
            name = _tool_name_of(call).lower()
            if "get_image_job" in name or "generate_image" in name:
                return True
    return False


def running_image_job_reply() -> Optional[str]:
    """Fallback text when the IDE has no get_image_job tool to drive."""
    try:
        from endpoints.core.image_jobs import active_mcp_image_job
    except Exception:
        return None
    job = active_mcp_image_job()
    if not job:
        return None
    dest = job.output_path or "images/generated.png"
    extra = ""
    phase = getattr(job, "phase", None)
    if not isinstance(phase, str) or not phase:
        phase = str(job.status)
    done = getattr(job, "done_count", None)
    items = getattr(job, "items", None)
    total = len(items) if isinstance(items, list) and items else getattr(job, "count", 1)
    if isinstance(done, int):
        extra = f" Progress {done}/{total}, phase {phase}."
    return (
        f"An image job is still running (id {job.id}, status {job.status}). "
        f"{job.wait_text}{extra} "
        f"Do not stop. Do not tell the user the PNG will appear later in {dest}. "
        "The next tool call must be get_image_job or Shell — not a status essay. "
        "Do not switch models. Keep the HTML pointing at those local paths. "
        f"If get_image_job is available, call it with job_id={job.id}."
    )


def last_user_text(data: ChatCompletionRequest) -> str:
    for message in reversed(data.messages or []):
        if message.role == "user":
            return _content_text(message.content)
    return ""


def user_says_images_missing(data: ChatCompletionRequest) -> bool:
    """True when the last user line says the PNGs never landed."""
    text = last_user_text(data).lower()
    if not text:
        return False
    mentions = any(
        word in text for word in ("image", "png", "logo", "header", "download")
    )
    missing = any(
        phrase in text
        for phrase in (
            "not there",
            "not here",
            "not downloaded",
            "aren't there",
            "are not there",
            "missing",
            "didn't download",
            "did not download",
            "never downloaded",
            "no png",
            "no image",
        )
    )
    return mentions and missing


def _recent_tool_text(data: ChatCompletionRequest) -> str:
    parts: list[str] = []
    for message in reversed(data.messages or []):
        if message.role in ("tool", "function"):
            parts.append(_content_text(message.content))
            continue
        break
    return "\n".join(reversed(parts))


def _shell_args_reference_dests(args: str, dests: list[str]) -> bool:
    """True when Shell args name this job's PNG dests, not a substring collision."""
    from common.image_paths import safe_rel_png_path

    text = str(args or "")
    if "curl" in text and "/v1/images/" in text:
        return True
    quoted: set[str] = set()
    for match in re.finditer(r"'([^']+)'|\"([^\"]+)\"", text):
        token = match.group(1) or match.group(2)
        if token.lower().endswith(".png"):
            quoted.add(safe_rel_png_path(token))
    needed = {safe_rel_png_path(dest) for dest in dests if dest}
    if not needed:
        return False
    return needed.issubset(quoted)


def _last_assistant_was_image_shell(data: ChatCompletionRequest, job) -> bool:
    from common.image_paths import job_output_paths

    dests = job_output_paths(job)
    for message in reversed(data.messages or []):
        if message.role == "assistant" and message.tool_calls:
            for call in message.tool_calls:
                name = _tool_name_of(call).lower()
                args = str(getattr(getattr(call, "function", None), "arguments", "") or "")
                if name in SHELL_TOOL_NAMES or name.endswith("shell"):
                    if _shell_args_reference_dests(args, dests):
                        return True
            return False
        if message.role == "user":
            return False
    return False


def _pngs_confirmed_on_disk(data: ChatCompletionRequest, job) -> bool:
    from common.image_paths import job_output_paths, tool_result_has_pngs

    return tool_result_has_pngs(_recent_tool_text(data), job_output_paths(job))


def _user_ask_without_hint(data: ChatCompletionRequest) -> str:
    """Mixed user ask only — drop the injected hint so new4/ examples stay examples."""
    text = mixed_source_text(data)
    if MIXED_IMAGE_HINT_MARK in text:
        text = text.split(MIXED_IMAGE_HINT_MARK, 1)[0]
    return text


def _chat_project_folder(data: ChatCompletionRequest) -> str:
    """Site folder from the mixed ask (pbptours), if the user named one."""
    from common.image_prompts import images_folder, site_folder

    text = _user_ask_without_hint(data)
    folder = site_folder(text)
    if folder:
        return folder
    dest = images_folder(text)
    if dest and "/" in dest:
        return dest.split("/", 1)[0]
    return ""


def _chat_waited_on_job(data: ChatCompletionRequest, job) -> bool:
    """True when this chat already polled or waited on this job id."""
    job_id = str(getattr(job, "id", "") or "")
    if not job_id:
        return False
    for message in data.messages or []:
        if job_id in _content_text(message.content):
            return True
        for call in message.tool_calls or []:
            args = str(
                getattr(getattr(call, "function", None), "arguments", "") or ""
            )
            if job_id in args:
                return True
    return False


def _chat_curled_job_dests(data: ChatCompletionRequest, job) -> bool:
    """True when this chat already ran Shell curl/ls for this job's PNG dests."""
    from common.image_paths import job_output_paths

    dests = job_output_paths(job)
    for message in data.messages or []:
        if message.role != "assistant":
            continue
        for call in message.tool_calls or []:
            name = _tool_name_of(call).lower()
            args = str(
                getattr(getattr(call, "function", None), "arguments", "") or ""
            )
            if name in SHELL_TOOL_NAMES or name.endswith("shell"):
                if _shell_args_reference_dests(args, dests):
                    return True
    return False


def _job_matches_this_chat(data: ChatCompletionRequest, job) -> bool:
    """False when a leftover job is for a different site folder than this chat.

    A folder-less leftover (plain images/logo.png) is not every new chat.
    Only treat it as this chat if we already waited on the job id, the user
    named that dest, or the job is still queued/running (just started here).
    """
    from common.image_paths import job_output_paths, job_project_folders

    if _chat_waited_on_job(data, job):
        return True
    if _chat_curled_job_dests(data, job):
        return True
    chat_folder = _chat_project_folder(data)
    job_folders = job_project_folders(job)
    dests = job_output_paths(job)
    blob = _user_ask_without_hint(data).lower()
    if any(dest.lower() in blob for dest in dests if dest):
        return True
    if getattr(job, "status", "") in ("queued", "running"):
        if not job_folders:
            return True
        if not chat_folder:
            return True
        return chat_folder in job_folders
    if not job_folders:
        return False
    if not chat_folder:
        # The job was scoped to a specific site (pbptours/images/...) but
        # this chat names no folder at all. Do not silently match — that
        # let an unrelated site's leftover job get downloaded into a
        # folder-less follow-up. Require an explicit dest/folder mention.
        return False
    return chat_folder in job_folders


async def await_gpu_busy_image_response(data: ChatCompletionRequest):
    """Same as gpu_busy_image_response, but pace running jobs before returning."""
    try:
        from common.image_paths import IMAGE_POLL_WAIT_S
        from endpoints.core.image_jobs import active_mcp_image_job
    except Exception:
        return gpu_busy_image_response(data)

    job = active_mcp_image_job()
    if job and getattr(job, "status", "") in ("queued", "running"):
        await asyncio.sleep(IMAGE_POLL_WAIT_S)
    return gpu_busy_image_response(data)


def _matching_mixed_job(data: ChatCompletionRequest):
    """Active or unsaved job that belongs to this mixed chat, if any."""
    try:
        from endpoints.core.image_jobs import (
            active_mcp_image_job,
            get_mcp_image_job,
            recent_mcp_image_jobs,
        )
    except Exception:
        return None

    busy = active_mcp_image_job()
    if busy and _job_matches_this_chat(data, busy):
        return busy

    for job in recent_mcp_image_jobs():
        if job.status not in ("done", "error"):
            continue
        if not (job.urls or job.status == "done"):
            continue
        if _chat_waited_on_job(data, job):
            return job

    done = get_mcp_image_job()
    if (
        done
        and done.status in ("done", "error")
        and (done.urls or done.status == "done")
        and _job_matches_this_chat(data, done)
    ):
        return done

    for job in recent_mcp_image_jobs():
        if job.status not in ("done", "error"):
            continue
        if not (job.urls or job.status == "done"):
            continue
        if getattr(job, "client_saved", False):
            continue
        if _job_matches_this_chat(data, job):
            return job
    return None


def _is_fresh_mixed_image_ask(data: ChatCompletionRequest) -> bool:
    """True on a new page+images or redo line, not a tool result."""
    if last_role(data) in ("tool", "function"):
        return False
    text = _last_ask_text(data)
    return _text_is_mixed_image(text) or _text_is_image_redo(text)


def _job_flag(job, name: str) -> bool:
    """True only for a real True bool (unittest Mock auto-attrs are truthy)."""
    return getattr(job, name, False) is True


def _job_gpu_files_missing(job) -> bool:
    """True when every timestamped generated-*.png URL on this job is gone."""
    from common.gpu_mode import is_public_generated_png
    from common.image_paths import (
        download_pairs_from_job,
        generated_png_name_from_url,
        gpu_generated_file_missing,
    )

    pairs = download_pairs_from_job(job)
    stamped = [
        url
        for url, _ in pairs
        if is_public_generated_png(generated_png_name_from_url(url))
    ]
    if not stamped:
        return False
    return all(gpu_generated_file_missing(url) for url in stamped)


def _recent_curl_failed(data: ChatCompletionRequest) -> bool:
    """True when a recent assistant or tool result shows a curl 404.

    VS Code often omits a tool-role `ls`, so scan assistant text too. Do not
    match the invented `curl -fsSL` command (no colon after curl).
    """
    parts: list[str] = []
    for message in reversed(data.messages or []):
        if message.role in ("tool", "function"):
            parts.append(_content_text(message.content))
            continue
        if message.role == "assistant":
            parts.append(_content_text(message.content))
            if parts:
                break
            continue
        if message.role == "user":
            break
    blob = "\n".join(reversed(parts)).lower()
    if "404" in blob:
        return True
    return bool(re.search(r"curl:\s*\(", blob))


def _job_download_attempts(job) -> int:
    try:
        return int(getattr(job, "download_attempts", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _job_covers_planned_dests(job, planned: list[dict]) -> bool:
    """True when this job already has every dest the mixed planner wants."""
    from common.image_paths import job_output_paths, safe_rel_png_path

    have = {safe_rel_png_path(path) for path in job_output_paths(job)}
    need = {
        safe_rel_png_path(str(row.get("output_path") or ""))
        for row in planned or []
        if isinstance(row, dict)
    }
    need.discard("")
    if not need:
        return True
    return need <= have


def _download_stop_text(job, *, files_missing: bool) -> str:
    """404 only when the GPU file is gone. Otherwise keep the living URLs."""
    if files_missing:
        return IMAGE_DOWNLOAD_STOP_NOTE
    from common.image_paths import image_download_note, living_download_pairs

    pairs = living_download_pairs(job)
    if not pairs:
        return IMAGE_DOWNLOAD_STOP_NOTE
    extra = image_download_note(pairs)
    return "\n".join(
        part for part in (IMAGE_DOWNLOAD_UNCONFIRMED_NOTE, extra) if part
    )


def _should_reuse_mixed_job(data: ChatCompletionRequest, job) -> bool:
    """False for a leftover done job this chat never waited on, or dead URLs."""
    if job is None:
        return False
    if not _job_matches_this_chat(data, job):
        return False
    if getattr(job, "status", "") in ("queued", "running"):
        return True
    if user_says_images_missing(data):
        return True
    if _text_is_image_redo(_last_ask_text(data)) and not _chat_waited_on_job(
        data, job
    ):
        return False
    if _is_fresh_mixed_image_ask(data) and not _chat_waited_on_job(data, job):
        return False
    if _job_gpu_files_missing(job):
        if _job_flag(job, "is_requeue") or _job_flag(job, "dead_requeued"):
            return True
        return False
    if _job_download_attempts(job) >= IMAGE_DOWNLOAD_MAX_ATTEMPTS:
        return True
    if _chat_waited_on_job(data, job):
        return True
    return True


def _planned_mixed_items(data: ChatCompletionRequest) -> list[dict[str, str]]:
    from common.image_prompts import (
        images_folder,
        plan_mixed_images,
        rewrite_comfy_prompt,
        site_folder,
    )

    last = _last_ask_text(data)
    if _text_is_image_redo(last):
        from common.image_prompts import plan_image_redo

        site = _chat_project_folder(data) or site_folder(mixed_source_text(data))
        items = plan_image_redo(last, site)
        if items:
            return items
    text = mixed_source_text(data)
    items = plan_mixed_images(text)
    if items:
        return items
    dest_dir = images_folder(text, site_folder(text))
    return [
        {
            "prompt": rewrite_comfy_prompt("wide photographic scene"),
            "output_path": f"{dest_dir}/generated.png",
        }
    ]


async def ensure_mixed_image_job(
    data: ChatCompletionRequest, api_base: Optional[str] = None
):
    """Queue Comfy from a mixed user line. The 9B does not submit the batch."""
    if not is_mixed_image_request(data):
        return None
    if last_role(data) in ("tool", "function"):
        return None
    existing = _matching_mixed_job(data)
    planned = _planned_mixed_items(data)
    if existing and _should_reuse_mixed_job(data, existing):
        covers = _job_covers_planned_dests(existing, planned)
        if (
            covers
            or _chat_waited_on_job(data, existing)
            or user_says_images_missing(data)
        ):
            if user_says_images_missing(data):
                try:
                    existing.client_saved = False
                except Exception:
                    pass
            return existing
    if not _is_fresh_mixed_image_ask(data):
        return None

    items = planned
    prompts = [str(row.get("prompt") or "") for row in items]
    try:
        from endpoints.core.image_jobs import start_mcp_image_job
    except Exception:
        return None
    if (
        existing
        and _chat_waited_on_job(data, existing)
        and _job_gpu_files_missing(existing)
        and not _job_flag(existing, "dead_requeued")
    ):
        try:
            existing.dead_requeued = True
        except Exception:
            pass
    job, _kind = await start_mcp_image_job(
        items=items,
        seed=None,
        restore=True,
        api_base=api_base or "",
        wait_text=image_job_wait_text(prompts=prompts),
        wait_s=image_job_wait_seconds(prompts=prompts),
    )
    if existing and _job_flag(existing, "dead_requeued"):
        try:
            job.is_requeue = True
        except Exception:
            pass
    xlogger.info(f"Mixed chat queued image job {job.id} ({_kind}, {len(items)} dests)")
    return job


async def prepare_mixed_image_turn(
    data: ChatCompletionRequest, api_base: Optional[str] = None
):
    """Start a mixed job if needed, then wait or download. None means the 9B may run."""
    await ensure_mixed_image_job(data, api_base)
    return await await_gpu_busy_image_response(data)


def _messages_since_last_user(data: ChatCompletionRequest):
    messages = list(data.messages or [])
    last_user = -1
    for index, message in enumerate(messages):
        if message.role == "user":
            last_user = index
    if last_user < 0:
        return messages
    return messages[last_user + 1 :]


def _chat_is_faking_images(data: ChatCompletionRequest) -> bool:
    """True when a tool is drawing PNGs with Pillow/SVG instead of the GPU job.

    Only tool arguments and tool results count. Assistant prose is ignored so
    our own 'do not write generate_images.py' note cannot loop.
    """
    blob_parts: list[str] = []
    for message in _messages_since_last_user(data):
        if message.role in ("tool", "function"):
            blob_parts.append(_content_text(message.content))
        for call in message.tool_calls or []:
            blob_parts.append(
                str(getattr(getattr(call, "function", None), "arguments", "") or "")
            )
    return bool(FAKE_IMAGE_SCRIPT_RE.search("\n".join(blob_parts)))


def _refuse_fake_pngs(data: ChatCompletionRequest, job) -> object:
    """Stop Pillow/SVG stand-ins and re-curl the GPU PNGs if they exist."""
    if not _chat_is_faking_images(data) or not is_mixed_image_request(data):
        return None
    if job and getattr(job, "status", "") in ("queued", "running"):
        xlogger.info(f"Image job {job.id}: refusing Pillow/SVG while still rendering")
        return _drive_running_image_job(data, job)
    if (
        job
        and getattr(job, "urls", None)
        and getattr(job, "status", "") in ("done", "error")
        and _job_matches_this_chat(data, job)
    ):
        if _job_flag(job, "pillow_redownload"):
            xlogger.info(
                f"Image job {job.id}: Pillow/SVG again; not resetting download cap"
            )
            return text_response(data, FAKE_PNG_NOTE)
        try:
            job.client_saved = False
            job.pillow_redownload = True
        except Exception:
            pass
        xlogger.info(
            f"Image job {job.id}: re-curling GPU PNGs after Pillow/SVG stand-in"
        )
        return _drive_image_download(data, job, extra_note=FAKE_PNG_NOTE)
    xlogger.info("Refusing Pillow/SVG stand-in with no matching GPU URLs")
    return text_response(data, FAKE_PNG_NOTE)


def gpu_busy_image_response(data: ChatCompletionRequest):
    """Keep the agent loop alive while Comfy owns the GPU, then save PNGs."""
    try:
        from endpoints.core.image_jobs import active_mcp_image_job
    except Exception:
        return None

    job = _matching_mixed_job(data)
    if job and job.status in ("queued", "running"):
        refused = _refuse_fake_pngs(data, job)
        if refused:
            return refused
        return _drive_running_image_job(data, job)

    if not job:
        job = active_mcp_image_job()
        if job:
            refused = _refuse_fake_pngs(data, job)
            if refused:
                return refused
            return _drive_running_image_job(data, job)
        return None

    refused = _refuse_fake_pngs(data, job)
    if refused:
        return refused
    if job.status not in ("done", "error") or not job.urls:
        return None

    missing = user_says_images_missing(data)
    if missing:
        job.client_saved = False

    waiting = (
        chat_is_waiting_on_images(data)
        or _history_has_image_tools(data)
        or missing
        or _chat_waited_on_job(data, job)
    )
    if not waiting or _job_flag(job, "client_saved"):
        return None
    if _job_flag(job, "download_stopped") and not missing:
        return None
    if not missing and not _job_matches_this_chat(data, job):
        xlogger.info(
            f"Image job {job.id} dests are for another folder; "
            "not driving a download on this chat"
        )
        return None
    if (
        not missing
        and _text_is_image_redo(_last_ask_text(data))
        and not _chat_waited_on_job(data, job)
    ):
        xlogger.info(
            f"Image job {job.id} is a leftover batch; "
            "not curling it on a logo/image redo"
        )
        return None
    if (
        not missing
        and _is_fresh_mixed_image_ask(data)
        and not _chat_waited_on_job(data, job)
    ):
        xlogger.info(
            f"Image job {job.id} is a leftover batch; "
            "not curling it on a new mixed ask"
        )
        return None

    if last_role(data) in ("tool", "function") and _last_assistant_was_image_shell(
        data, job
    ):
        if _pngs_confirmed_on_disk(data, job):
            job.client_saved = True
            xlogger.info(f"Image job {job.id} PNGs confirmed on disk")
            return None

    curl_failed = _recent_curl_failed(data)
    files_missing = _job_gpu_files_missing(job)
    try:
        attempts = int(getattr(job, "download_attempts", 0) or 0)
    except (TypeError, ValueError):
        attempts = 0
    if (
        (curl_failed or files_missing or attempts >= IMAGE_DOWNLOAD_MAX_ATTEMPTS)
        and not missing
    ):
        xlogger.info(
            f"Image job {job.id} download stop "
            f"(404={curl_failed} missing={files_missing} attempts={attempts})"
        )
        try:
            job.download_stopped = True
        except Exception:
            pass
        return text_response(
            data,
            _download_stop_text(job, files_missing=files_missing),
        )

    return _drive_image_download(data, job)


def _align_job_dests_for_chat(data: ChatCompletionRequest, job) -> None:
    """Rename collapsed logo-N dests and put them under this chat's site folder."""
    from common.image_paths import align_item_dests

    items = getattr(job, "items", None)
    if not isinstance(items, (list, tuple)):
        return
    align_item_dests(items, site_folder=_chat_project_folder(data))
    dests = [getattr(item, "output_path", "") for item in items]
    if dests:
        try:
            job.output_path = dests[0]
        except Exception:
            pass


def _drive_running_image_job(data: ChatCompletionRequest, job) -> object:
    from common.image_paths import (
        IMAGE_POLL_WAIT_S,
        image_poll_wait_command,
        image_running_note,
        match_tool_name,
    )

    _align_job_dests_for_chat(data, job)
    names = _request_tool_names(data)
    poll_name = match_tool_name(names, IMAGE_POLL_TOOL_NAMES)
    if poll_name:
        xlogger.info(f"Image job {job.id} running; requesting {poll_name}")
        return tool_call_response(
            data,
            [(poll_name, {"job_id": job.id, "wait_s": IMAGE_POLL_WAIT_S})],
            content=image_running_note(job),
        )
    # Invent Shell, never get_image_job. Cursor Cloud runs Shell even when it
    # is not in this request's tools array; it does not run an MCP poll tool
    # that was omitted from the request (that is the 1 Hz loop).
    # Do not curl mid-batch — Copilot copies the generated-*.png pattern and
    # GETs planets that are still on the GPU.
    shell_name = match_tool_name(names, SHELL_TOOL_NAMES) or "Shell"
    command = image_poll_wait_command(job)
    xlogger.info(f"Image job {job.id} running; {shell_name} wait (poll tool not listed)")
    return tool_call_response(
        data,
        [
            (
                shell_name,
                {
                    "command": command,
                    "description": "Wait; images are still rendering",
                    "block_until_ms": (IMAGE_POLL_WAIT_S + 5) * 1000,
                },
            )
        ],
        content=image_running_note(job),
    )


def _drive_image_download(
    data: ChatCompletionRequest, job, extra_note: str = ""
) -> object:
    from common.image_paths import (
        image_download_command,
        image_download_note,
        living_download_pairs,
        match_tool_name,
    )

    _align_job_dests_for_chat(data, job)
    pairs = living_download_pairs(job)
    command = image_download_command(pairs)
    if not command:
        return None
    notes = []
    if extra_note:
        notes.append(extra_note)
    if job.status == "error":
        notes.append(
            f"Job {job.id} did not finish ({job.error or 'unknown error'}). "
            f"{len(pairs)} image(s) rendered before that; saving those now. "
            "Call generate_image again for any still-missing assets."
        )
    note = image_download_note(pairs)
    if note:
        notes.append(note)
    names = _request_tool_names(data)
    shell_name = match_tool_name(names, SHELL_TOOL_NAMES) or "Shell"
    try:
        attempts = int(getattr(job, "download_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    try:
        job.download_attempts = attempts
    except Exception:
        pass
    xlogger.info(f"Image job {job.id} done; {shell_name} curl PNGs")
    return tool_call_response(
        data,
        [
            (
                shell_name,
                {
                    "command": command,
                    "description": "Download generated PNGs from the API URLs",
                },
            )
        ],
        content="\n".join(notes) or None,
    )


def _chat_has_generate_image(data: ChatCompletionRequest) -> bool:
    from common.image_paths import match_tool_name

    return match_tool_name(_request_tool_names(data), ("generate_image",)) is not None


def mixed_image_hint(
    api_base: Optional[str] = None,
    *,
    has_generate_image: bool = False,
    pngs_ready: bool = False,
) -> str:
    """Tell a remote agent to write the page after the server-owned PNGs exist."""
    flux = extra_seconds("comfy", "flux_s")
    qwen = extra_seconds("comfy", "qwen_image_s")
    flux_s = format_duration(flux) if flux else "a few minutes"
    qwen_s = format_duration(qwen) if qwen else "a few minutes"
    llm_s = format_duration(ready_seconds("llm"))
    ready_line = (
        "The GPU PNGs already exist at the planned paths (or this API is curling them). "
        "Write HTML/CSS/JS now. Do not create generate_images.py and do not overwrite "
        "those .png files.\n"
        if pngs_ready
        else ""
    )
    return (
        f"{MIXED_IMAGE_HINT_MARK} "
        "This is a new task. Do not apologize, and do not mention repeated "
        "errors or prior attempts — just do the steps below. "
        "Do not treat this as a single image prompt. "
        "Do not paste the webpage into chat. "
        f"{ready_line}"
        "Do not fake images with SVG, CSS shapes, Pillow/PIL circles, emoji, "
        "placeholder URLs, or Unsplash. "
        "Do not write generate_images.py or any Python drawing script. "
        "Do not convert SVG to PNG. If a curl 404s, wait — do not invent "
        "substitute images. "
        "Unless the user explicitly asked for SVG, every image is a generated PNG. "
        "Do not use the browser. Do not use Cursor's built-in GenerateImage tool. "
        "Do not use generate_image. The server already queued the PNG job.\n"
        "Required steps:\n"
        "  1. If the PNG files are not on disk yet, keep using the wait or download "
        "tool this API requested (Shell or get_image_job). Do not invent "
        "/v1/images/generated-*.png URLs. Do not write the page until those files exist.\n"
        "  2. After the PNGs exist: HTML/CSS/JS — call the Write or StrReplace tool "
        "so real files land in the workspace. Point img src at the planned local PNG "
        "paths (images/logo.png). A fenced code block is not a file. "
        "Write/StrReplace cannot save PNG bytes.\n"
        "     Prefix qwen-image: only when the PNG must show readable words "
        "(logo, poster, button). Hero/header photos are Flux — describe a scene, "
        "not a website or UI.\n"
        f"     Flux draft: about {flux_s} to render each. Qwen-Image: about {qwen_s} each. "
        f"The coding model reloads once at the end (about {llm_s}).\n"
        "The GPU is exclusive: one Comfy batch at a time (several PNGs per batch is OK)."
    )


def mixed_source_text(data: ChatCompletionRequest) -> str:
    """The user line that asked for a page plus images (unwrap IDE tags)."""
    last_mixed = ""
    for message in data.messages or []:
        if message.role != "user":
            continue
        raw = _content_text(message.content)
        for query in _queries_in(raw):
            if _text_is_mixed_image(query):
                last_mixed = query
    if last_mixed:
        return last_mixed
    return _unwrap_query(last_user_raw(data))


def _hint_with_plan(api_base: Optional[str], data: ChatCompletionRequest) -> str:
    from common.image_prompts import (
        MIXED_PLAN_MARK,
        format_mixed_image_plan,
        mixed_image_plan_text,
        plan_image_redo,
        site_folder,
        user_asked_for_svg,
    )

    has_tool = _chat_has_generate_image(data)
    pngs_ready = False
    try:
        job = _matching_mixed_job(data)
        pngs_ready = bool(job and _job_flag(job, "client_saved"))
    except Exception:
        pngs_ready = False
    hint = mixed_image_hint(
        api_base, has_generate_image=has_tool, pngs_ready=pngs_ready
    )
    last = _last_ask_text(data)
    if _text_is_image_redo(last):
        site = _chat_project_folder(data) or site_folder(mixed_source_text(data))
        plan = format_mixed_image_plan(
            plan_image_redo(last, site),
            asked_for_svg=user_asked_for_svg(last),
            has_generate_image=has_tool,
        )
    else:
        plan = mixed_image_plan_text(
            mixed_source_text(data), has_generate_image=has_tool
        )
    if plan and MIXED_PLAN_MARK not in hint:
        hint = f"{hint}\n{plan}"
    return hint


def _insert_hint(content: str, hint: str) -> str:
    """Put the brief inside <userRequest>/<user_query> so Copilot sees it."""
    if MIXED_IMAGE_HINT_MARK in content:
        return content
    matches = list(QUERY_TAG_RE.finditer(content))
    if matches:
        last = matches[-1]
        tag = last.group(1)
        inner = (last.group(2) or "").rstrip()
        rewritten = f"{inner}\n\n{hint}"
        return (
            content[: last.start()]
            + f"<{tag}>\n{rewritten}\n</{tag}>"
            + content[last.end() :]
        )
    return content + "\n" + hint


def inject_mixed_image_hint(
    data: ChatCompletionRequest, api_base: Optional[str] = None
) -> None:
    if not is_mixed_image_request(data):
        return
    hint = _hint_with_plan(api_base, data)
    for message in reversed(data.messages or []):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            if MIXED_IMAGE_HINT_MARK in content:
                return
            message.content = _insert_hint(content, hint)
            return
        if isinstance(content, list):
            for part in content:
                if MIXED_IMAGE_HINT_MARK in (getattr(part, "text", None) or ""):
                    return
            message.content = list(content) + [
                ChatCompletionMessagePart(type="text", text=hint)
            ]
        return


def requested_image_prompt(
    data: ChatCompletionRequest, explicit_only: bool = False
) -> Optional[str]:
    """Image prompt from the user's actual line, never the Agent wrapper.

    When the LLM is loaded, only explicit “generate an image …” lines run
    Comfy. Mixed coding + image requests stay with the agent.
    In Comfy mode any short description is a prompt, except mixed tasks.
    """
    if last_role(data) in ("tool", "function"):
        return None
    if is_mixed_image_request(data):
        return None
    if already_made_image(data) and not has_new_user_after_image(data):
        return None
    raw = last_user_raw(data)
    text = _unwrap_query(raw)
    if not text:
        return None
    if any(marker.lower() in text.lower() for marker in AGENT_MARKERS):
        return None
    if len(text) > MAX_IMAGE_PROMPT_CHARS or META_IMAGE_RE.search(text):
        return None
    if _is_meta_wrapper_text(text):
        return None
    if explicit_only and is_coding_task(text):
        return None
    match = IMAGE_GEN_RE.match(text)
    if match:
        prompt = (match.group(1) or "").strip()
        if explicit_only and not IMAGE_NOUN_RE.search(text):
            return None
        return prompt or None
    if explicit_only:
        return None
    return text


def should_yield_comfy_to_llm(data: ChatCompletionRequest) -> bool:
    """True when Comfy owns the GPU but this turn needs the coding model."""
    if last_role(data) in ("tool", "function"):
        return True
    return is_mixed_image_request(data)


def last_llm_profile_name() -> str:
    """Last LLM profile for a Comfy→LLM handoff (never 'comfy')."""
    try:
        from select_model import last_profile

        name = last_profile()
    except Exception:
        name = None
    if name and name.lower() not in GPU_ALIASES and name.lower() != "comfy":
        return name
    return "qwen"


def yield_comfy_to_llm_response(data: ChatCompletionRequest):
    """Reload the last LLM so mixed Agent / tool turns can keep coding."""
    busy = gpu_busy_image_response(data)
    if busy:
        return busy
    if switch_in_progress():
        return llm_not_ready_response(data)
    name = last_llm_profile_name()
    start_switch(name)
    return text_response(data, llm_loading_text(name))


def requested_image_count(prompt: str) -> tuple[int, str]:
    """How many separate Flux jobs a chat line asked for, and the cleaned prompt."""

    text = (prompt or "").strip()
    match = IMAGE_COUNT_RE.match(text)
    if not match:
        return 1, text
    raw = (match.group("num") or "1").lower()
    if raw in _IMAGE_COUNT_WORDS:
        count = _IMAGE_COUNT_WORDS[raw]
    else:
        try:
            count = int(raw)
        except ValueError:
            return 1, text
    count = max(1, min(count, MAX_CHAT_IMAGES))
    rest = (match.group("rest") or "").strip()
    return count, rest or text


IMAGE_DOWNLOAD_HINT = (
    "These URLs are on this API host. The markdown preview above is the picture."
)


def _image_url_block(filenames: list[str], api_base: Optional[str] = None) -> str:
    names = [name for name in (filenames or []) if name]
    if not names:
        return "No generated images for this turn yet."
    lines = [f"{len(names)} image(s) from this turn:"]
    for index, name in enumerate(names, start=1):
        url = public_image_url(name, api_base=api_base)
        lines.append(f"\n{index}. {name}\n![]({url})\n{url}")
    lines.append("\n" + IMAGE_DOWNLOAD_HINT)
    return "\n".join(lines)


def turn_image_names(extra: Optional[str] = None) -> list[str]:
    names = [path.name for path in recent_generated_files()]
    if extra and extra not in names:
        names.append(extra)
    return names


def gpu_is_comfy() -> bool:
    return (read_mode().get("mode") or "llm").lower() == "comfy"


def switch_in_progress() -> bool:
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 180:
        return True
    return False


def llm_not_ready_response(data: ChatCompletionRequest):
    busy = gpu_busy_image_response(data)
    if busy:
        return busy
    if switch_in_progress():
        name = ""
        try:
            name = LOCK.read_text(encoding="utf-8").strip().lower()
        except OSError:
            name = ""
        if name in GPU_ALIASES or name == "comfy":
            return text_response(data, comfy_starting_text())
        return text_response(data, llm_loading_text(name))
    return text_response(data, llm_not_ready_text())


def comfy_idle_response(data: ChatCompletionRequest, api_base: Optional[str] = None):
    busy = gpu_busy_image_response(data)
    if busy:
        return busy
    if already_made_image(data):
        return text_response(
            data,
            "That request already has previews (same chat turn). "
            "Send a new short description for another picture, or switch to qwen.\n\n"
            + _image_url_block(turn_image_names(), api_base=api_base),
        )
    return text_response(data, COMFY_IDLE)


def image_ready_response(
    data: ChatCompletionRequest,
    filename: str,
    api_base: Optional[str] = None,
    *,
    restore: bool = False,
    count: int = 1,
):
    this = image_job_wait_text(last_user_text(data), restore=restore, count=count)
    another = image_job_wait_text("", restore=restore)
    text = (
        _image_url_block(turn_image_names(filename), api_base=api_base)
        + f"\n\nThis picture: {this}"
        + "\nSend another short description for a different picture, or switch to qwen."
        + f"\nAnother picture: {another}"
    )
    return text_response(data, text)


def handle_if_requested(data: ChatCompletionRequest, api_base: Optional[str] = None):
    if is_help_request(data):
        return text_response(data, help_text(api_base=api_base))
    if is_list_request(data):
        return text_response(data, list_text())
    if is_restart_request(data):
        if not start_restart():
            return text_response(
                data,
                "Restart is not available on this host. Send help for the chat phrases.",
            )
        return text_response(data, restart_reply_text())

    query = last_user_text(data)
    if is_save_image_request(query):
        return text_response(data, pasted_download_text(query, api_base or public_api_base()))

    name = requested_profile(data)
    if not name:
        token = _match_any(SWITCH_RE, data)
        if token:
            unknown = token.group(1)
            return text_response(
                data,
                f"Unknown model {unknown!r}. Send 'list models' or 'help'.",
            )
        return None
    start_switch(name)
    return text_response(data, switch_reply_text(name))

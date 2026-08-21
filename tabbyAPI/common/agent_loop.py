"""Detect Agent tool-call loops and inject a stop-searching hint."""

from __future__ import annotations

import json
import re
from common.logger import xlogger
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest

LOOP_HINT = (
    "[Anti-loop] You have been repeating the same search/read tool. "
    "Do not call that tool again. Make the edit or give a short status now. "
    "A tool is allowed only if the path or query is new."
)
POLL_DONE_HINT = (
    "[Anti-loop] The image job is finished. Do not call get_image_job again. "
    "The PNGs are already at output_path. Finish the webpage now and stop polling."
)
HINT_MARK = "[Anti-loop]"
FUNCTION_RE = re.compile(
    r"<function=([^>\s]+)|\"name\"\s*:\s*\"([^\"]+)\"|tool_name['\"]?\s*[:=]\s*['\"]([^'\"]+)",
    re.I,
)
SEARCH_TOOLS = {
    "read",
    "grep",
    "glob",
    "glob_file_search",
    "semanticsearch",
    "semantic_search",
    "codebase_search",
    "list_dir",
    "listdir",
    "readfile",
    "read_file",
}
POLL_TOOLS = {
    "get_image_job",
    "generate_image",
}
EDIT_TOOLS = {
    "write",
    "strreplace",
    "search_replace",
    "editnotebook",
    "edit_notebook",
    "delete",
    "applypatch",
}


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


def _tool_name_from_call(call) -> str:
    func = getattr(call, "function", None)
    name = getattr(func, "name", None) if func is not None else None
    return (name or "").strip().lower()


def _tool_args_from_call(call) -> str:
    func = getattr(call, "function", None)
    args = getattr(func, "arguments", None) if func is not None else None
    if args is None:
        return ""
    if isinstance(args, str):
        return re.sub(r"\s+", " ", args).strip()
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except TypeError:
        return str(args)


def _names_from_text(text: str) -> list[str]:
    names = []
    for match in FUNCTION_RE.finditer(text or ""):
        name = next((group for group in match.groups() if group), "")
        if name:
            names.append(name.strip().lower())
    return names


def assistant_tool_turns(data: ChatCompletionRequest) -> list[tuple[str, str]]:
    """Recent assistant tool turns as (name, args_fingerprint)."""
    turns = []
    for message in data.messages or []:
        if message.role != "assistant":
            continue
        calls = message.tool_calls or []
        if calls:
            name = _tool_name_from_call(calls[0])
            args = _tool_args_from_call(calls[0])
            turns.append((name, args))
            continue
        text = _content_text(message.content)
        names = _names_from_text(text)
        if names:
            turns.append((names[0], re.sub(r"\s+", " ", text)[:400]))
    return turns


def _is_poll_tool(name: str) -> bool:
    text = (name or "").strip().lower()
    return text in POLL_TOOLS or text.endswith("get_image_job")


def _image_job_still_running() -> bool:
    try:
        from endpoints.core.image_jobs import active_mcp_image_job
    except Exception:
        return False
    return bool(active_mcp_image_job())


def looks_like_tool_loop(data: ChatCompletionRequest) -> bool:
    turns = assistant_tool_turns(data)
    if len(turns) < 3:
        return False

    last_three = turns[-3:]
    if last_three[0] == last_three[1] == last_three[2]:
        if _is_poll_tool(last_three[0][0]) and _image_job_still_running():
            return False
        return True

    last_four = turns[-4:]
    names = [name for name, _ in last_four]
    if len(last_four) >= 4 and all(names) and len(set(names)) == 1:
        if _is_poll_tool(names[0]) and _image_job_still_running():
            return False
        return True

    search_streak = 0
    for name, _ in reversed(turns):
        if name in EDIT_TOOLS:
            break
        if name in SEARCH_TOOLS or not name:
            search_streak += 1
        else:
            break
        if search_streak >= 8:
            return True
    return False


def already_has_hint(data: ChatCompletionRequest) -> bool:
    for message in reversed(data.messages or []):
        if HINT_MARK in _content_text(message.content):
            return True
    return False


def inject_loop_break(data: ChatCompletionRequest) -> bool:
    """Append a user hint when the Agent is looping. Returns True if injected."""
    if already_has_hint(data) or not looks_like_tool_loop(data):
        return False
    turns = assistant_tool_turns(data)
    hint = LOOP_HINT
    if turns and _is_poll_tool(turns[-1][0]):
        hint = POLL_DONE_HINT
    data.messages.append(ChatCompletionMessage(role="user", content=hint))
    xlogger.info("Injected anti-loop hint into chat completion request")
    return True

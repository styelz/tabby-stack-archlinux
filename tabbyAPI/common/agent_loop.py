"""Detect Agent tool-call loops and inject a stop-searching hint."""

from __future__ import annotations

import json
import re
from common.logger import xlogger
from common.noop_edits import HINT_MARK as NOOP_HINT_MARK, NOOP_EDIT_HINT, tool_result_is_zero_change
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
# gpu_busy_image_response invents a Shell "sleep N; echo job '<id>' still
# running; ls -l ..." call (see common/image_paths.image_poll_wait_command)
# whenever an MCP poll tool is not listed — which is the common case for
# GitHub Copilot / Cursor Cloud. That command is identical turn after turn
# by design, so it must be recognized as a poll, the same as get_image_job,
# or the anti-loop hint fires mid-render and appends a fake "user" message
# that makes every image-job helper misread the conversation (last_role /
# last_user_text) as a plain, non-image turn.
_IMAGE_WAIT_ARGS_RE = re.compile(r"\bsleep\s+\d+\b.*\bstill running\b", re.I | re.S)
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


def _is_image_wait_repeat(name: str, args: str) -> bool:
    """True for our own invented Shell wait/poll command, any tool name.

    The name varies by client (Shell, run_in_terminal, bash, ...) so this
    checks the fingerprint instead of a fixed name list.
    """
    if _is_poll_tool(name):
        return True
    return bool(_IMAGE_WAIT_ARGS_RE.search(args or ""))


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
        name, args = last_three[0]
        if _is_image_wait_repeat(name, args) and _image_job_still_running():
            return False
        return True

    last_four = turns[-4:]
    names = [name for name, _ in last_four]
    if len(last_four) >= 4 and all(names) and len(set(names)) == 1:
        if _is_image_wait_repeat(names[0], last_four[0][1]) and _image_job_still_running():
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
        text = _content_text(message.content)
        if HINT_MARK in text or NOOP_HINT_MARK in text:
            return True
    return False


def inject_zero_change_hint(data: ChatCompletionRequest) -> bool:
    """If the last tool result was a 0-change apply, force another real edit."""
    if already_has_hint(data):
        return False
    for message in reversed(data.messages or []):
        if message.role == "tool" and tool_result_is_zero_change(message.content):
            data.messages.append(
                ChatCompletionMessage(role="user", content=NOOP_EDIT_HINT.strip())
            )
            xlogger.info("Injected anti-noop hint into chat completion request")
            return True
        if message.role in ("assistant", "user"):
            break
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

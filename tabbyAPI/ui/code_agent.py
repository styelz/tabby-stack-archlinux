"""Server-side jailed project-tool loop for UI Code mode."""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Optional

from common.logger import xlogger
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest
from endpoints.OAI.types.common import ChatCompletionStreamOptions
from endpoints.OAI.types.tools import Function, ToolSpec
from ui import workspace

MAX_CODE_TURNS = 16
MAX_BRIEF_FILES = 80
MAX_PLAN_NUDGES = 2
MAX_STEP_RESULT = 500
MAX_STEP_ARG = 200
AGENT_STEP_MARK = "tabby-agent-step:"
AGENT_KINDS = ("agent", "ask", "plan")
CODE_SYSTEM = (
    "You are coding in a workspace project folder on this Tabby Stack host. "
    "This conversation is one thread in that workspace; extra chats share the "
    "same files. The user can create, upload, and attach files; attached files "
    "are included in their message. Use the file tools (Write, StrReplace, Read, "
    "Rename, Delete, List) to create and edit text files. Use OptimizeImage to "
    "compress, resize, or convert project images. If they attach a picture and "
    "ask to remove a border or frame, wait for the new GPU PNG; do not fake it "
    "with CSS, background-size, or JavaScript. Use Shell to run project "
    "commands in this workspace's container (cwd is /work). Do not create "
    "placeholder files when an attached project image can be processed with "
    "OptimizeImage. Do not dump whole files in chat. Do not try to run the site "
    "for the user; they have preview. Point img src at the planned local paths. "
    "Generated assets for an HTML website are automatically converted to "
    "web-optimized files and their code references are updated after rendering. "
    "When you are done, give a short summary of what you wrote or optimized. "
    "Earlier messages in this thread are the brief, including an "
    "<approved_plan> or the last Plan reply. Implement that; do not ask for "
    "a new spec."
)
ASK_SYSTEM = (
    "You are answering questions about a workspace project folder on this "
    "Tabby Stack host. This conversation is one thread in that workspace; "
    "extra chats share the same files. Use this thread and the project "
    "files together: earlier Plan or Ask turns are part of the brief. Do "
    "not ignore them. Use Read and List to inspect files. Do not create, "
    "edit, delete, rename, or optimize files. Do not run Shell. Do not "
    "implement changes. Answer clearly from the conversation and the project."
)
PLAN_SYSTEM = (
    "You are Plan mode for a workspace project folder on this Tabby Stack "
    "host. This conversation is one thread in that workspace; extra chats "
    "share the same files. A workspace file list is already in this prompt; "
    "only Read a file if you need its contents. Do not List just to confirm "
    "the file list. If a plan is already in this thread, revise that plan; "
    "do not start from a blank page. Do not create, edit, delete, rename, "
    "or optimize files, and do not run Shell. "
    "Your assistant message is the plan the user will review, then click "
    "Build to implement. Never say you will write a plan — write it now. "
    "Use markdown with these headings:\n"
    "## Goal\n## Files\n## Steps\n## Assets\n## Risks\n"
    "Files: concrete relative paths and what each one is for. "
    "Steps: numbered and specific enough to implement without asking again. "
    "Assets: dest paths for images (logo/text vs photo), or None. "
    "Do not implement."
)
PLAN_CONTRACT_MARK = "<plan_mode>"
PLAN_USER_SUFFIX = (
    "\n\n<plan_mode>\n"
    "Write the full implementation plan now as markdown with headings Goal, "
    "Files, Steps, Assets, and Risks. Name concrete relative paths. Number "
    "the steps. Do not implement. Do not announce a plan — this reply is "
    "the plan. The user will click Build later.\n"
    "</plan_mode>"
)
PLAN_RETRY = (
    "That reply was not a plan. Write the complete implementation plan now "
    "as markdown with headings Goal, Files, Steps, Assets, and Risks. "
    "Include concrete file paths and numbered steps. Do not implement. "
    "Do not call tools unless you must Read a specific existing file. "
    "Do not say you will write a plan later."
)
_PLAN_HEADING = re.compile(r"(?m)^#{1,3}\s+\S")
_PLAN_STEPS = re.compile(r"(?m)^\s*(?:\d+[\.\)]\s+\S|[-*]\s+\S.{8,})")
_PLAN_PATH = re.compile(
    r"\b[\w./-]+\.(?:html?|css|js|mjs|ts|tsx|jsx|json|md|py|svg|png|jpe?g|webp|gif)\b",
    re.I,
)
_PLAN_PREAMBLE = re.compile(
    r"(?is)\b(?:i will now|i(?:'m| am) (?:going to|about to)|"
    r"let me (?:now )?(?:design|write|create|plan)|"
    r"i have (?:read|listed|checked) (?:the )?(?:project|directory|workspace))\b"
)
_MUTATE_KINDS = frozenset(
    ("write", "replace", "delete", "rename", "optimize", "shell")
)
_READONLY_TOOLS = frozenset(("read", "list"))
_READONLY_REFUSE = (
    "This prompt mode is read-only. Use Read or List, or switch to Agent to "
    "change files."
)
BUILD_PROMPT = "Implement the approved plan above. Do not wait for more confirmation."


def normalize_agent(value: Any) -> str:
    kind = str(value or "").strip().lower()
    return kind if kind in AGENT_KINDS else "agent"


def _system_for_agent(agent: str) -> str:
    kind = normalize_agent(agent)
    if kind == "ask":
        return ASK_SYSTEM
    if kind == "plan":
        return PLAN_SYSTEM
    return CODE_SYSTEM


def _content_has_mark(content: Any, mark: str) -> bool:
    if isinstance(content, str):
        return mark in content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and mark in str(part.get("text") or ""):
                return True
            if isinstance(part, str) and mark in part:
                return True
    return False


def _append_text_content(content: Any, extra: str) -> Any:
    if isinstance(content, list):
        parts = [part if isinstance(part, dict) else part for part in content]
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                part["text"] = str(part.get("text") or "") + extra
                return parts
        return [{"type": "text", "text": extra.lstrip()}] + parts
    return str(content or "") + extra


def _plain_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content or "")


def is_build_prompt(text: Any) -> bool:
    return _plain_content(text).strip().startswith(BUILD_PROMPT)


def attach_plan_user_contract(messages: list) -> None:
    """Pin the plan-mode contract on the last user turn (server-only)."""
    for item in reversed(messages):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if is_build_prompt(content):
            return
        if _content_has_mark(content, PLAN_CONTRACT_MARK):
            return
        item["content"] = _append_text_content(content, PLAN_USER_SUFFIX)
        return


def _strip_think(text: str) -> str:
    return re.sub(r"(?is)<think>.*?</think>", " ", text or "").strip()


def plan_looks_complete(text: str) -> bool:
    """True when the reply is a reviewable plan, not a promise to write one."""
    body = _strip_think(text)
    if not body:
        return False
    headings = len(_PLAN_HEADING.findall(body))
    steps = len(_PLAN_STEPS.findall(body))
    paths = len(_PLAN_PATH.findall(body))
    if _PLAN_PREAMBLE.search(body) and headings < 2 and steps < 3:
        return False
    if headings >= 3 and len(body) >= 160:
        return True
    if headings >= 2 and steps >= 3 and len(body) >= 160:
        return True
    if steps >= 5 and paths >= 1 and len(body) >= 240:
        return True
    return False


def workspace_file_brief(username: str, chat_id: str) -> str:
    """Short path list so a fresh workspace thread is not blind."""
    if not username or not chat_id:
        return ""
    try:
        data = workspace.listing(username, chat_id)
    except Exception:
        return ""
    files = [
        str(row.get("path") or "")
        for row in data.get("files") or []
        if isinstance(row, dict) and row.get("kind") != "dir" and row.get("path")
    ]
    if not files:
        return "Workspace files: (empty project)."
    files.sort()
    extra = 0
    if len(files) > MAX_BRIEF_FILES:
        extra = len(files) - MAX_BRIEF_FILES
        files = files[:MAX_BRIEF_FILES]
    count = int(data.get("count") or len(files) + extra)
    text = ", ".join(files)
    if extra:
        text += f", …and {extra} more"
    return f"Workspace files ({count}): {text}."


def code_system_for(username: str, chat_id: str, agent: str = "agent") -> str:
    base = _system_for_agent(agent)
    brief = workspace_file_brief(username, chat_id)
    if not brief:
        return base
    return f"{base}\n\n{brief}"


_WRITE_NAMES = (
    "write",
    "write_file",
    "write_to_file",
    "create_file",
)
_REPLACE_NAMES = (
    "strreplace",
    "search_replace",
    "replace_in_file",
    "edit_file",
)
_READ_NAMES = ("read", "read_file", "readfile")
_DELETE_NAMES = ("delete", "delete_file", "remove_file")
_RENAME_NAMES = ("rename", "rename_file", "move_file", "mv")
_LIST_NAMES = ("list", "list_dir", "listdir", "list_files")
_OPTIMIZE_NAMES = ("optimizeimage", "optimize_image", "compress_image", "resize_image")
_SHELL_NAMES = ("shell", "bash", "run_command", "run_terminal_cmd")


def code_tool_specs(agent: str = "agent") -> list[ToolSpec]:
    specs = [
        ToolSpec(
            type="function",
            function=Function(
                name="Write",
                    description="Create or overwrite a text file in this workspace's project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path, e.g. index.html"},
                        "contents": {"type": "string", "description": "Full file contents"},
                    },
                    "required": ["path", "contents"],
                },
            ),
        ),
        ToolSpec(
            type="function",
            function=Function(
                name="StrReplace",
                description="Replace one exact string in a project file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            ),
        ),
        ToolSpec(
            type="function",
            function=Function(
                name="Rename",
                description="Rename or move a project file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Current relative path"},
                        "to": {"type": "string", "description": "New relative path"},
                    },
                    "required": ["path", "to"],
                },
            ),
        ),
        ToolSpec(
            type="function",
            function=Function(
                name="Read",
                description="Read a project file.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ),
        ToolSpec(
            type="function",
            function=Function(
                name="Delete",
                description="Delete a project file.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ),
        ToolSpec(
            type="function",
            function=Function(
                name="List",
                description="List files in the project (optional subdirectory).",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory to list, or omit for the project root.",
                        }
                    },
                },
            ),
        ),
        ToolSpec(
            type="function",
            function=Function(
                name="OptimizeImage",
                description=(
                    "Optimize, resize, convert, or crop a uniform border from one "
                    "existing project image. Omit output_path and format to safely "
                    "optimize it in place. Set trim_border to crop a white or black "
                    "frame; do not use CSS for that."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path of the existing project image.",
                        },
                        "output_path": {
                            "type": "string",
                            "description": (
                                "Optional destination. Omit to overwrite in place, or when "
                                "converting to create name.optimized.ext."
                            ),
                        },
                        "max_width": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8192,
                            "description": "Optional maximum width while preserving aspect ratio.",
                        },
                        "max_height": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8192,
                            "description": "Optional maximum height while preserving aspect ratio.",
                        },
                        "quality": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 82,
                            "description": "JPEG or WebP quality.",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["original", "png", "jpeg", "webp", "gif"],
                            "default": "original",
                        },
                        "lossless": {
                            "type": "boolean",
                            "default": False,
                            "description": "Use lossless encoding when writing WebP.",
                        },
                        "trim_border": {
                            "type": "boolean",
                            "default": False,
                            "description": (
                                "Crop a uniform edge color (white card frame, letterbox) "
                                "before optimizing."
                            ),
                        },
                    },
                    "required": ["path"],
                },
            ),
        ),
        ToolSpec(
            type="function",
            function=Function(
                name="Shell",
                description=(
                    "Run a command in this workspace's project container. cwd is /work. "
                    "Use for installs, builds, and checks. Prefer file tools for edits."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to run, e.g. python3 -m http.server --help",
                        }
                    },
                    "required": ["command"],
                },
            ),
        ),
    ]
    if normalize_agent(agent) == "agent":
        return specs
    return [spec for spec in specs if _kind(spec.function.name) in _READONLY_TOOLS]


def _arg_path(args: dict) -> str:
    for key in ("path", "file_path", "target_file", "output_path"):
        value = args.get(key)
        if value:
            return str(value).strip()
    return ""


def _arg_contents(args: dict) -> str:
    for key in ("contents", "content", "text"):
        if key in args and args[key] is not None:
            return args[key] if isinstance(args[key], str) else str(args[key])
    return ""


def _arg_dest(args: dict) -> str:
    for key in ("to", "dest", "new_path", "destination"):
        value = args.get(key)
        if value:
            return str(value).strip()
    return ""


def _arg_bool(args: dict, key: str, default: bool = False) -> bool:
    if key not in args or args.get(key) is None:
        return default
    value = args.get(key)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _tool_pairs(message) -> list[tuple[str, dict, str]]:
    pairs: list[tuple[str, dict, str]] = []
    for call in getattr(message, "tool_calls", None) or []:
        func = getattr(call, "function", None)
        name = getattr(func, "name", None) if func is not None else None
        if not name:
            continue
        raw = getattr(func, "arguments", "") or ""
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"arguments": raw}
            args = parsed if isinstance(parsed, dict) else {"value": parsed}
        call_id = str(getattr(call, "id", "") or "")
        pairs.append((str(name), args, call_id))
    return pairs


def _kind(name: str) -> str:
    from common.image_paths import match_tool_name

    key = (name or "").strip()
    if match_tool_name([key], _WRITE_NAMES):
        return "write"
    if match_tool_name([key], _REPLACE_NAMES):
        return "replace"
    if match_tool_name([key], _READ_NAMES):
        return "read"
    if match_tool_name([key], _DELETE_NAMES):
        return "delete"
    if match_tool_name([key], _RENAME_NAMES):
        return "rename"
    if match_tool_name([key], _LIST_NAMES):
        return "list"
    if match_tool_name([key], _OPTIMIZE_NAMES):
        return "optimize"
    if match_tool_name([key], _SHELL_NAMES):
        return "shell"
    return ""


def execute_tool(
    username: str,
    chat_id: str,
    name: str,
    args: dict,
    agent: str = "agent",
) -> tuple[str, str]:
    """Run one tool. Returns (status_label, result_text)."""
    kind = _kind(name)
    if normalize_agent(agent) != "agent" and kind in _MUTATE_KINDS:
        return "Tool error", _READONLY_REFUSE
    rel = _arg_path(args)
    if kind == "shell":
        command = str(args.get("command") or args.get("cmd") or "").strip()
        if not command:
            return "Tool error", "command is required"
        from ui import codebox

        try:
            code, output = codebox.run_shell(username, chat_id, command)
        except codebox.CodeboxError as exc:
            return "Tool error", str(exc)
        text = output if output.strip() else "(no output)"
        if code:
            text = f"exit {code}\n{text}"
        return "Running command", text
    if kind == "list":
        prefix = rel.rstrip("/")
        if prefix in (".",):
            prefix = ""
        rows = workspace.list_files(username, chat_id)
        if prefix:
            rows = [
                row
                for row in rows
                if row["path"] == prefix or row["path"].startswith(prefix + "/")
            ]
        if not rows:
            return "Listing files", "(empty project)" if not prefix else f"{prefix}: no files"
        listed = "\n".join(f"{row['path']} ({row['size']} bytes)" for row in rows)
        return "Listing files", listed
    if not rel:
        return "Tool error", "path is required"
    if kind == "write":
        written = workspace.write_text(username, chat_id, rel, _arg_contents(args))
        return f"Writing {written}", f"Wrote {written}"
    if kind == "replace":
        old = str(args.get("old_string") or args.get("oldStr") or "")
        new = str(args.get("new_string") or args.get("newStr") or "")
        workspace.str_replace(username, chat_id, rel, old, new)
        return f"Editing {rel}", f"Updated {rel}"
    if kind == "read":
        return f"Reading {rel}", workspace.read_text(username, chat_id, rel)
    if kind == "delete":
        workspace.delete_file(username, chat_id, rel)
        return f"Deleting {rel}", f"Deleted {rel}"
    if kind == "rename":
        dest = _arg_dest(args)
        if not dest:
            return "Tool error", "to is required"
        written = workspace.rename_file(username, chat_id, rel, dest)
        return f"Renaming {written}", f"Renamed {rel} to {written}"
    if kind == "optimize":
        result = workspace.optimize_image(
            username,
            chat_id,
            rel,
            output_path=str(args.get("output_path") or ""),
            max_width=args.get("max_width"),
            max_height=args.get("max_height"),
            quality=args.get("quality", 82),
            output_format=str(args.get("format") or "original"),
            lossless=_arg_bool(args, "lossless", False),
            trim_border=_arg_bool(args, "trim_border", False),
        )
        return f"Optimizing {result['path']}", json.dumps(result, separators=(",", ":"))
    return (
        "Tool error",
        f"Unknown tool {name!r}. Use Write, StrReplace, Read, Rename, Delete, List, OptimizeImage, or Shell.",
    )


def _assistant_message(response):
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    return getattr(choices[0], "message", None)


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


def summarize_writes(paths: list[str]) -> str:
    names = [name for name in paths if name]
    if not names:
        return "No files were written."
    if len(names) == 1:
        return f"Wrote {names[0]}. Download the zip from Files when you want a copy."
    return (
        "Wrote " + ", ".join(names) + ". Download the zip from Files when you want a copy."
    )


def truncate_step_text(text: Any, limit: int = MAX_STEP_RESULT) -> str:
    body = str(text or "")
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + "…"


def tool_step_args(args: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(args, dict):
        return out
    path = _arg_path(args)
    if path:
        out["path"] = path
    dest = _arg_dest(args)
    if dest:
        out["to"] = dest
    cmd = str(args.get("command") or args.get("cmd") or "").strip()
    if cmd:
        out["command"] = truncate_step_text(cmd, MAX_STEP_ARG)
    return out


def tool_step_payload(name: str, args: dict, label: str, result: str) -> dict[str, Any]:
    return {
        "type": "tool",
        "name": str(name or ""),
        "label": str(label or ""),
        "args": tool_step_args(args if isinstance(args, dict) else {}),
        "result": truncate_step_text(result),
    }


def format_agent_step_comment(step: dict[str, Any]) -> str:
    return f"{AGENT_STEP_MARK} {json.dumps(step, separators=(',', ':'), ensure_ascii=False)}"


def remaining_stream_text(final: str, streamed: str) -> str:
    """Text still needed after live content deltas. Empty means do not dump again."""
    final = str(final or "")
    streamed = str(streamed or "")
    if not final or final == streamed:
        return ""
    if streamed and final.startswith(streamed):
        return final[len(streamed) :]
    return final


def parse_completion_chunk(raw: Any) -> Optional[dict[str, Any]]:
    if raw is None or raw == "[DONE]":
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    text = str(raw).strip()
    if text.startswith("data:"):
        text = text[5:].strip()
    if not text or text == "[DONE]":
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tool_calls_from_dumps(dumps: Any) -> Optional[list]:
    from endpoints.OAI.types.tools import Tool, ToolCall

    if not dumps:
        return None
    calls = []
    for item in dumps:
        if isinstance(item, ToolCall):
            calls.append(item)
            continue
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "")
        if not name:
            continue
        args = fn.get("arguments")
        if isinstance(args, dict):
            args = json.dumps(args, separators=(",", ":"))
        else:
            args = str(args or "")
        fields: dict[str, Any] = {
            "function": Tool(name=name, arguments=args),
            "type": "function",
        }
        if item.get("id"):
            fields["id"] = str(item["id"])
        if item.get("index") is not None:
            fields["index"] = item["index"]
        calls.append(ToolCall(**fields))
    return calls or None


def message_from_stream(
    content: str,
    reasoning: str,
    tool_dumps: Any,
) -> ChatCompletionMessage:
    return ChatCompletionMessage(
        role="assistant",
        content=content or None,
        reasoning_content=reasoning or None,
        tool_calls=_tool_calls_from_dumps(tool_dumps),
    )


def _chunk_error(parsed: dict[str, Any]) -> str:
    err = parsed.get("error")
    if not err:
        return ""
    if isinstance(err, dict):
        return str(err.get("message") or "Chat failed")
    return str(err)


def sse_for_code_event(
    event: tuple,
    data: ChatCompletionRequest,
    *,
    chunk_id: str,
    created: int,
) -> list[Any]:
    """Turn one iter_code_turns event into SSE comments or OpenAI chunk JSON."""
    from common.phrase_switch import stream_chat_delta
    from images.chat import STATUS_MARK
    from sse_starlette import ServerSentEvent

    kind = event[0]
    if kind == "status":
        return [ServerSentEvent(comment=f"{STATUS_MARK} {event[1]}")]
    if kind == "reasoning":
        return [
            stream_chat_delta(
                data,
                {"reasoning_content": event[1]},
                chunk_id=chunk_id,
                created=created,
            )
        ]
    if kind == "content":
        return [
            stream_chat_delta(
                data,
                {"content": event[1]},
                chunk_id=chunk_id,
                created=created,
            )
        ]
    if kind == "demote":
        return [ServerSentEvent(comment=format_agent_step_comment({"type": "demote"}))]
    if kind == "tool":
        payload = event[1] if isinstance(event[1], dict) else {"type": "tool"}
        return [ServerSentEvent(comment=format_agent_step_comment(payload))]
    return []


async def stream_code_completion(
    working: ChatCompletionRequest,
    prompt,
    embeddings,
    request,
    model_path,
    disconnect_handler,
) -> AsyncIterator[tuple[str, Any]]:
    """Yield reasoning/content deltas, then ('turn', message, usage, error)."""
    from common.assistant_text import strip_apology_sse
    from endpoints.OAI.utils.chat_completion import stream_generate_chat_completion

    streamed = working.model_copy(update={"stream": True, "n": 1})
    content = ""
    reasoning = ""
    tool_dumps: Any = None
    usage = None
    error = ""
    async for raw in strip_apology_sse(
        stream_generate_chat_completion(
            prompt, embeddings, streamed, request, model_path, disconnect_handler
        )
    ):
        parsed = parse_completion_chunk(raw)
        if parsed is None:
            continue
        err = _chunk_error(parsed)
        if err:
            error = err
            break
        if parsed.get("usage") is not None:
            usage = parsed["usage"]
        choice = (parsed.get("choices") or [{}])[0] or {}
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            delta = {}
        reason_delta = delta.get("reasoning_content") or ""
        content_delta = delta.get("content") or ""
        if reason_delta:
            reasoning += str(reason_delta)
            yield ("reasoning", str(reason_delta))
        if content_delta:
            content += str(content_delta)
            yield ("content", str(content_delta))
        tools = delta.get("tool_calls")
        if tools:
            tool_dumps = tools
    yield ("turn", message_from_stream(content, reasoning, tool_dumps), usage, error)


async def iter_code_turns(
    data: ChatCompletionRequest,
    disconnect_handler,
    username: str,
    chat_id: str,
    agent: str = "agent",
) -> AsyncIterator[tuple[str, Any]]:
    """Yield status, live tokens, tool steps, usage, then ('done', text, written_paths)."""
    from common import model
    from common.networking import DisconnectHandler, generation_request
    from endpoints.OAI.utils.chat_completion import apply_chat_template

    container = getattr(model, "container", None)
    if not container or not getattr(container, "loaded", False):
        yield ("done", "No model is loaded, so files were not written.", [])
        return
    if getattr(container, "prompt_template", None) is None:
        yield ("done", "Chat is disabled because no prompt template is set.", [])
        return
    model_path = getattr(container, "model_dir", None)
    if model_path is None:
        yield ("done", "No model is loaded, so files were not written.", [])
        return
    request = generation_request(
        getattr(disconnect_handler, "request", None) if disconnect_handler else None
    )

    kind = normalize_agent(agent)
    empty = "empty project" in workspace_file_brief(username, chat_id)
    working = data.model_copy(
        update={
            "stream": True,
            "n": 1,
            "tools": code_tool_specs(kind),
            "tool_choice": "none" if kind == "plan" and empty else "auto",
            "messages": list(data.messages or []),
            "stream_options": ChatCompletionStreamOptions(include_usage=True),
        }
    )
    written: list[str] = []
    last_text = ""
    plan_nudges = 0
    nested = DisconnectHandler(
        request=request,
        description="ui code tools",
        abort_event=getattr(disconnect_handler, "abort_event", None),
    )
    for _turn in range(MAX_CODE_TURNS):
        if disconnect_handler:
            await disconnect_handler.poll()
        message = None
        usage = None
        turn_error = ""
        try:
            prompt, embeddings = await apply_chat_template(working)
            async for event in stream_code_completion(
                working, prompt, embeddings, request, model_path, nested
            ):
                if event[0] in ("reasoning", "content"):
                    yield event
                elif event[0] == "turn":
                    message, usage, turn_error = event[1], event[2], event[3]
        except Exception as exc:
            xlogger.warning(f"UI code turn failed: {exc}")
            yield ("done", last_text or f"Coding stopped: {exc}", written)
            return
        if usage is not None:
            yield ("usage", usage)
        if turn_error:
            yield ("done", last_text or f"Coding stopped: {turn_error}", written)
            return
        if message is None:
            yield ("done", last_text or "The model returned an empty reply.", written)
            return
        last_text = _content_text(getattr(message, "content", None))
        pairs = _tool_pairs(message)
        if not pairs:
            if (
                kind == "plan"
                and plan_nudges < MAX_PLAN_NUDGES
                and not plan_looks_complete(last_text)
            ):
                plan_nudges += 1
                if last_text.strip():
                    yield ("demote",)
                working.messages.append(message)
                working.messages.append(
                    ChatCompletionMessage(role="user", content=PLAN_RETRY)
                )
                yield ("status", "Writing plan")
                continue
            yield ("done", last_text, written)
            return
        if last_text.strip():
            yield ("demote",)
        working.messages.append(message)
        for name, args, call_id in pairs:
            try:
                label, result = execute_tool(username, chat_id, name, args, agent=kind)
            except (ValueError, FileNotFoundError, OSError) as exc:
                label, result = "Tool error", str(exc)
            if (
                label.startswith("Writing ")
                or label.startswith("Editing ")
                or label.startswith("Renaming ")
                or label.startswith("Optimizing ")
            ):
                path = (
                    label.removeprefix("Optimizing ")
                    if label.startswith("Optimizing ")
                    else _arg_path(args)
                )
                if path and path not in written:
                    written.append(path)
            yield ("status", label)
            yield ("tool", tool_step_payload(name, args, label, result))
            working.messages.append(
                ChatCompletionMessage(
                    role="tool",
                    content=result,
                    tool_call_id=call_id or None,
                )
            )
    yield ("done", last_text or summarize_writes(written), written)


def final_code_text(text: str, written: list[str]) -> str:
    body = (text or "").strip()
    if body:
        return body
    return summarize_writes(written)

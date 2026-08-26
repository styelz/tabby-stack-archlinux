"""Server-side jailed project-tool loop for UI Code mode."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from common.logger import xlogger
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest
from endpoints.OAI.types.tools import Function, ToolSpec
from ui import workspace

MAX_CODE_TURNS = 16
MAX_BRIEF_FILES = 80
AGENT_KINDS = ("agent", "ask", "plan")
CODE_SYSTEM = (
    "You are coding in a workspace project folder on this Tabby Stack host. "
    "This conversation is one thread in that workspace; extra chats share the "
    "same files. The user can create, upload, and attach files; attached files "
    "are included in their message. Use the file tools (Write, StrReplace, Read, "
    "Rename, Delete, List) to create and edit text files. Use OptimizeImage to "
    "compress, resize, or convert project images. Use Shell to run project "
    "commands in this workspace's container (cwd is /work). Do not create "
    "placeholder files when an attached project image can be processed with "
    "OptimizeImage. Do not dump whole files in chat. Do not try to run the site "
    "for the user; they have preview. Point img src at the planned local paths. "
    "Generated assets for an HTML website are automatically converted to "
    "web-optimized files and their code references are updated after rendering. "
    "When you are done, give a short summary of what you wrote or optimized."
)
ASK_SYSTEM = (
    "You are answering questions about a workspace project folder on this "
    "Tabby Stack host. This conversation is one thread in that workspace; "
    "extra chats share the same files. Use Read and List to inspect files. "
    "Do not create, edit, delete, rename, or optimize files. Do not run Shell. "
    "Do not implement changes. Answer clearly from the project."
)
PLAN_SYSTEM = (
    "You are planning work in a workspace project folder on this Tabby Stack "
    "host. This conversation is one thread in that workspace; extra chats "
    "share the same files. Use Read and List if you need context. Do not "
    "create, edit, delete, rename, or optimize files, and do not run Shell. "
    "Write a concrete plan with steps. Do not implement. The user will click "
    "Build when they want the plan carried out."
)
_MUTATE_KINDS = frozenset(
    ("write", "replace", "delete", "rename", "optimize", "shell")
)
_READONLY_TOOLS = frozenset(("read", "list"))
_READONLY_REFUSE = (
    "This prompt mode is read-only. Use Read or List, or switch to Agent to "
    "change files."
)


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
                    "Optimize, resize, or convert one existing project image. "
                    "Omit output_path and format to safely optimize it in place."
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
            lossless=bool(args.get("lossless", False)),
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


async def iter_code_turns(
    data: ChatCompletionRequest,
    disconnect_handler,
    username: str,
    chat_id: str,
    agent: str = "agent",
) -> AsyncIterator[tuple[str, Any]]:
    """Yield ('status', label) then ('done', text, written_paths)."""
    from common import model
    from common.assistant_text import strip_response_apologies
    from common.networking import DisconnectHandler
    from endpoints.OAI.utils.chat_completion import apply_chat_template, generate_chat_completion

    request = getattr(disconnect_handler, "request", None) if disconnect_handler else None
    container = getattr(model, "container", None)
    if request is None or not container or not getattr(container, "loaded", False):
        yield ("done", "No model is loaded, so files were not written.", [])
        return
    if getattr(container, "prompt_template", None) is None:
        yield ("done", "Chat is disabled because no prompt template is set.", [])
        return
    model_path = getattr(container, "model_dir", None)
    if model_path is None:
        yield ("done", "No model is loaded, so files were not written.", [])
        return

    kind = normalize_agent(agent)
    working = data.model_copy(
        update={
            "stream": False,
            "n": 1,
            "tools": code_tool_specs(kind),
            "tool_choice": "auto",
            "messages": list(data.messages or []),
        }
    )
    written: list[str] = []
    last_text = ""
    nested = DisconnectHandler(
        request=request,
        description="ui code tools",
        abort_event=getattr(disconnect_handler, "abort_event", None),
    )
    for _turn in range(MAX_CODE_TURNS):
        if disconnect_handler:
            await disconnect_handler.poll()
        try:
            prompt, embeddings = await apply_chat_template(working)
            response = await generate_chat_completion(
                prompt, embeddings, working, request, model_path, nested
            )
            response = strip_response_apologies(response)
        except Exception as exc:
            xlogger.warning(f"UI code turn failed: {exc}")
            yield ("done", last_text or f"Coding stopped: {exc}", written)
            return
        message = _assistant_message(response)
        if message is None:
            yield ("done", last_text or "The model returned an empty reply.", written)
            return
        last_text = _content_text(getattr(message, "content", None))
        pairs = _tool_pairs(message)
        if not pairs:
            yield ("done", last_text, written)
            return
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

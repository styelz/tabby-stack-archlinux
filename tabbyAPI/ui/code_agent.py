"""Server-side file-tool loop for UI Code mode. No shell."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from common.logger import xlogger
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest
from endpoints.OAI.types.tools import Function, ToolSpec
from ui import workspace

MAX_CODE_TURNS = 16
CODE_SYSTEM = (
    "You are coding in a per-chat project folder on this Tabby Stack host. "
    "Use the file tools (Write, StrReplace, Read, Delete, List) to create and "
    "edit files. Do not dump whole files in chat. Do not use a shell and do "
    "not try to run the site. Point img src at the planned local paths. "
    "When you are done, give a short summary of what you wrote."
)

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
_LIST_NAMES = ("list", "list_dir", "listdir", "list_files")


def code_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            type="function",
            function=Function(
                name="Write",
                description="Create or overwrite a text file in this chat's project.",
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
    ]


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
    if match_tool_name([key], _LIST_NAMES):
        return "list"
    return ""


def execute_tool(username: str, chat_id: str, name: str, args: dict) -> tuple[str, str]:
    """Run one tool. Returns (status_label, result_text)."""
    kind = _kind(name)
    rel = _arg_path(args)
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
    return "Tool error", f"Unknown tool {name!r}. Use Write, StrReplace, Read, Delete, or List."


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

    working = data.model_copy(
        update={
            "stream": False,
            "n": 1,
            "tools": code_tool_specs(),
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
                label, result = execute_tool(username, chat_id, name, args)
            except (ValueError, FileNotFoundError, OSError) as exc:
                label, result = "Tool error", str(exc)
            if label.startswith("Writing ") or label.startswith("Editing "):
                path = _arg_path(args)
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

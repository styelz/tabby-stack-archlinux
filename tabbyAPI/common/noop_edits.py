"""Drop file-edit tool calls that would apply 0 changes.

Qwen 9B often emits StrReplace/ApplyPatch where old_string equals
new_string, or a patch with no +/− lines. The IDE applies that as
success with an empty diff, then the agent stops. Detect that before
the client runs the tool.
"""

from __future__ import annotations

import json
import re

NOOP_EDIT_HINT = (
    "\n[Anti-noop] That file edit would apply 0 changes "
    "(old_string equals new_string, or the patch has no added/removed lines). "
    "Call a tool now, do not explain what you would call. If you are unsure of "
    "the exact current text, call Read on that file first. Otherwise call the "
    "edit tool again: new_string must differ from old_string and must implement "
    "the requested change.\n"
)
NOOP_EDIT_HINT_LAST = (
    "\n[Anti-noop] That file edit would apply 0 changes. "
    "If you can make a real edit, call the tool now (new_string must differ). "
    "Otherwise reply in one short sentence: say you need to Read the file, "
    "or ask for the exact change. Do not emit another identical edit.\n"
)
NOOP_EMPTY_REPLY = (
    "That file edit would not have changed anything "
    "(the old text already matched the new text). "
    "I stopped instead of applying a no-op. "
    "Send the change again, or ask me to read the file first."
)
HINT_MARK = "[Anti-noop]"
MAX_RETRIES = 2

_EDIT_CANON = {
    "strreplace",
    "searchreplace",
    "replaceinfile",
    "replacestringinfile",
    "applypatch",
}
_REPLACE_CANON = {
    "strreplace",
    "searchreplace",
    "replaceinfile",
    "replacestringinfile",
}
_PATCH_CANON = {"applypatch"}
_OLD_KEYS = ("old_string", "oldString", "old_str", "oldText", "old_text")
_NEW_KEYS = ("new_string", "newString", "new_str", "newText", "new_text")
_PATCH_KEYS = ("input", "patch", "diff", "contents")
_ZERO_CHANGE_RE = re.compile(
    r"\b0 changes\b|"
    r"no changes (?:made|applied)|"
    r"old_string and new_string are (?:the )?identical|"
    r"identical to the current",
    re.I,
)


def _canon(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _args_dict(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str) or not arguments.strip():
        return {}
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first(args: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in args and args[key] is not None:
            return args[key]
    return None


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def patch_is_noop(patch: str) -> bool:
    """True when a unified / apply_patch diff does not change any line."""
    plus = []
    minus = []
    for line in (patch or "").splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            plus.append(line[1:])
        elif line.startswith("-"):
            minus.append(line[1:])
    if not plus and not minus:
        return True
    return plus == minus


def is_noop_edit(name: str, arguments) -> bool:
    canon = _canon(name)
    if canon not in _EDIT_CANON:
        return False
    args = _args_dict(arguments)
    if canon in _REPLACE_CANON:
        old = _first(args, _OLD_KEYS)
        new = _first(args, _NEW_KEYS)
        if old is None or new is None:
            return False
        return _as_text(old) == _as_text(new)
    if canon in _PATCH_CANON:
        patch = _first(args, _PATCH_KEYS)
        if patch is None:
            return False
        return patch_is_noop(_as_text(patch))
    return False


def is_noop_tool_dump(dumped: dict) -> bool:
    func = dumped.get("function") if isinstance(dumped, dict) else None
    if not isinstance(func, dict):
        return False
    return is_noop_edit(func.get("name") or "", func.get("arguments"))


def split_noop_tool_dumps(dumped: list) -> tuple[list, int]:
    """Return (kept dumps, dropped_count). Re-index kept streaming dumps."""
    kept = []
    dropped = 0
    for item in dumped or []:
        if is_noop_tool_dump(item):
            dropped += 1
            continue
        kept.append(item)
    for index, item in enumerate(kept):
        if isinstance(item, dict) and "index" in item:
            item["index"] = index
    return kept, dropped


def tool_result_is_zero_change(content) -> bool:
    if content is None:
        return False
    if isinstance(content, str):
        text = content
    else:
        parts = []
        for part in content:
            text = getattr(part, "text", None)
            if text:
                parts.append(text)
        text = "\n".join(parts)
    return bool(_ZERO_CHANGE_RE.search(text or ""))


# Names used by chat_completion / agent_loop
NOOP_EDIT_HINT = NOOP_EDIT_HINT
NOOP_EDIT_HINT_LAST = NOOP_EDIT_HINT_LAST
NOOP_EMPTY_REPLY = NOOP_EMPTY_REPLY
MAX_RETRIES = MAX_RETRIES
HINT_MARK = HINT_MARK
split_noop_tool_dumps = split_noop_tool_dumps

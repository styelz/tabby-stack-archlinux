#!/usr/bin/env python3
"""Configure tabby-stack from the shell: tsctl <section> key=value."""

from __future__ import annotations

import readline
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

TABBY_ROOT = Path(__file__).resolve().parents[1]
if str(TABBY_ROOT) not in sys.path:
    sys.path.insert(0, str(TABBY_ROOT))

from ui.settings import (  # noqa: E402
    SettingsError,
    load_settings,
    normalize_saver_key,
    save_settings,
)

USAGE = """\
tsctl — tabby-stack settings

  tsctl                         interactive menu (dialog) or shell
  tsctl list                    sections
  tsctl <section>               print keys and values
  tsctl <section> <key>         print one value
  tsctl <section> <key>=<value>
  tsctl <section> <key> <value>
  tsctl screensaver enable|disable|status
  tsctl restart                 restart TabbyAPI

Sections match Settings: network, model, screensaver, system, …
"""


def _sections(data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = data or load_settings()
    out = list(payload.get("tabby") or [])
    if payload.get("screensaver"):
        out.append(payload["screensaver"])
    if payload.get("system"):
        out.append(payload["system"])
    return out


def find_section(name: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    want = name.strip().lower().replace("-", "_")
    for section in _sections(data):
        if str(section.get("name") or "").lower() == want:
            return section
        if str(section.get("label") or "").lower().replace(" ", "_") == want:
            return section
    raise SettingsError(f"Unknown section {name}. Try: tsctl list")


def field_by_name(section: dict[str, Any], key: str) -> dict[str, Any]:
    want = key.strip()
    if section.get("name") == "screensaver":
        want = normalize_saver_key(want)
    for field in section.get("fields") or []:
        if field.get("name") == want:
            return field
        if field.get("env") == want:
            return field
    raise SettingsError(f"Unknown setting {section.get('name')}.{key}")


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def print_section(section: dict[str, Any]) -> int:
    print(f"{section.get('label') or section.get('name')}")
    desc = (section.get("description") or "").strip()
    if desc:
        print(desc)
    print()
    width = max((len(str(field.get("name") or "")) for field in section.get("fields") or []), default=8)
    for field in section.get("fields") or []:
        print(f"  {field['name']:<{width}}  {format_value(field.get('value'))}")
    return 0


def coerce_cli(spec: dict[str, Any], raw: str) -> Any:
    kind = spec.get("kind")
    text = raw.strip()
    if kind == "bool":
        return text.lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    return text


def apply_sets(section_name: str, pairs: list[tuple[str, str]]) -> dict[str, Any]:
    data = load_settings()
    section = find_section(section_name, data)
    name = str(section["name"])
    updates: dict[str, Any] = {}
    for key, raw in pairs:
        field = field_by_name(section, key)
        updates[field["name"]] = coerce_cli(field, raw)
    if name == "screensaver":
        return save_settings({"screensaver": updates})
    if name == "system":
        return save_settings({"system": updates})
    return save_settings({"tabby": {name: updates}})


def saver_status() -> int:
    data = load_settings()
    section = find_section("screensaver", data)
    print_section(section)
    active = subprocess.run(
        ["systemctl", "is-active", "tabby-saver"],
        capture_output=True,
        text=True,
        timeout=8,
    )
    enabled = subprocess.run(
        ["systemctl", "is-enabled", "tabby-saver"],
        capture_output=True,
        text=True,
        timeout=8,
    )
    print()
    print(f"  systemd     {(active.stdout or '').strip() or 'unknown'} / {(enabled.stdout or '').strip() or 'unknown'}")
    return 0


def restart_api() -> int:
    result = subprocess.run(
        ["systemctl", "--user", "restart", "tabbyapi"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        print(f"tsctl: restart failed: {err}", file=sys.stderr)
        return 1
    print("Restarted tabbyapi.")
    return 0


def report_save(data: dict[str, Any]) -> int:
    warning = str(data.get("reload_warning") or "").strip()
    if warning:
        print(warning, file=sys.stderr)
        return 1 if "systemd:" in warning else 0
    print("ok")
    return 0


def complete_words(cword: int, words: list[str]) -> list[str]:
    data = load_settings()
    sections = [str(section["name"]) for section in _sections(data)]
    extra = ["list", "help", "restart", "screensaver"]
    if cword <= 1:
        return sorted(set(sections + extra))
    try:
        section = find_section(words[1], data)
    except SettingsError:
        return []
    names = [str(field["name"]) for field in section.get("fields") or []]
    if section.get("name") == "screensaver":
        names.extend(["enable", "disable", "status", "timeout", "logout-timeout"])
    if cword == 2:
        return sorted(set(names))
    return []


def parse_pairs(tokens: list[str]) -> list[tuple[str, str]]:
    if not tokens:
        return []
    if len(tokens) == 2 and "=" not in tokens[0]:
        return [(tokens[0], tokens[1])]
    pairs = []
    for token in tokens:
        if "=" not in token:
            raise SettingsError(f"Expected key=value (got {token})")
        key, value = token.split("=", 1)
        pairs.append((key, value))
    return pairs


def run_dialog(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        ["dialog", "--backtitle", "tabby-stack", *args],
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.returncode, (result.stderr or "").strip()


def dialog_available() -> bool:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    from shutil import which

    return which("dialog") is not None


def tui() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(USAGE)
        return 0
    if dialog_available():
        return tui_dialog()
    return repl()


def tui_dialog() -> int:
    while True:
        data = load_settings()
        sections = _sections(data)
        items: list[str] = []
        for section in sections:
            items.extend([str(section["name"]), str(section.get("label") or section["name"])[:40]])
        code, choice = run_dialog(
            ["--title", "tsctl", "--menu", "Pick a section. Esc quits.", "20", "72", "12", *items]
        )
        if code != 0 or not choice:
            return 0
        section = find_section(choice, data)
        while True:
            fields = list(section.get("fields") or [])
            rows: list[str] = []
            for field in fields:
                rows.extend(
                    [
                        str(field["name"]),
                        f"{format_value(field.get('value'))}"[:42],
                    ]
                )
            extra = []
            if section["name"] == "screensaver":
                extra = ["enable", "Turn unit on", "disable", "Turn unit off"]
            code, key = run_dialog(
                [
                    "--title",
                    str(section.get("label") or section["name"]),
                    "--menu",
                    str(section.get("description") or "Edit a setting"),
                    "22",
                    "74",
                    "14",
                    *extra,
                    *rows,
                ]
            )
            if code != 0 or not key:
                break
            if key in ("enable", "disable"):
                body = save_settings({"screensaver": {"enabled": key == "enable"}})
                run_dialog(["--msgbox", str(body.get("reload_warning") or "ok"), "8", "60"])
                data = load_settings()
                section = find_section("screensaver", data)
                continue
            field = field_by_name(section, key)
            code, value = run_dialog(
                [
                    "--title",
                    str(field.get("label") or field["name"]),
                    "--inputbox",
                    str(field.get("description") or field["name"]),
                    "12",
                    "70",
                    format_value(field.get("value")),
                ]
            )
            if code != 0:
                continue
            try:
                body = apply_sets(str(section["name"]), [(str(field["name"]), value)])
            except (SettingsError, ValueError) as exc:
                run_dialog(["--msgbox", str(exc), "8", "60"])
                continue
            note = str(body.get("reload_warning") or "Saved.")
            run_dialog(["--msgbox", note, "8", "60"])
            data = load_settings()
            section = find_section(str(section["name"]), data)
    return 0


def repl() -> int:
    data = load_settings()
    names = [str(section["name"]) for section in _sections(data)]

    def completer(text: str, state: int) -> str | None:
        buf = readline.get_line_buffer()
        parts = buf.split()
        if len(parts) <= 1:
            options = [name for name in names + ["list", "help", "quit"] if name.startswith(text)]
        else:
            try:
                section = find_section(parts[0], data)
                options = [
                    str(field["name"])
                    for field in section.get("fields") or []
                    if str(field["name"]).startswith(text)
                ]
            except SettingsError:
                options = []
        return options[state] if state < len(options) else None

    try:
        readline.parse_and_bind("tab: complete")
        readline.set_completer(completer)
    except Exception:
        pass
    print("tsctl  (quit / q to leave, tab completes)")
    while True:
        try:
            line = input("tsctl> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line or line in ("q", "quit", "exit"):
            return 0
        try:
            code = dispatch(shlex.split(line))
        except SettingsError as exc:
            print(exc, file=sys.stderr)
            code = 1
        if code and code != 0:
            pass
    return 0


def dispatch(argv: list[str]) -> int:
    if not argv:
        return tui()
    if argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv[0] == "--complete":
        cword = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 1
        words = argv[2:] if len(argv) > 2 else []
        print(" ".join(complete_words(cword, words)))
        return 0
    if argv[0] == "list":
        for section in _sections():
            print(f"{section['name']}\t{section.get('label') or ''}")
        return 0
    if argv[0] == "restart":
        return restart_api()

    section_name = argv[0]
    rest = argv[1:]
    if section_name == "screensaver" and rest and rest[0] in ("enable", "disable", "status"):
        if rest[0] == "status":
            return saver_status()
        body = save_settings({"screensaver": {"enabled": rest[0] == "enable"}})
        return report_save(body)

    data = load_settings()
    section = find_section(section_name, data)
    if not rest:
        return print_section(section)
    if len(rest) == 1 and "=" not in rest[0]:
        field = field_by_name(section, rest[0])
        print(format_value(field.get("value")))
        return 0
    pairs = parse_pairs(rest)
    return report_save(apply_sets(str(section["name"]), pairs))


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return dispatch(args)
    except SettingsError as exc:
        print(f"tsctl: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

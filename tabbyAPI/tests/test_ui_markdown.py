"""Chat markdown fences. Keep in sync with ui/static/utils.js extractFences."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

UTILS_JS = Path(__file__).resolve().parents[1] / "ui" / "static" / "utils.js"

OPEN_RE = re.compile(r"^(\s*)(`{3,}|~{3,})[ \t]*([\w+-]*)(.*)$")

SAMPLE = """\
Here is a simple, robust shell script to find all broken symbolic links on a specific drive.

### The Script: `find_broken_links.sh`

```bash
#!/bin/bash
TARGET_PATH="/"
find "$TARGET_PATH" -xtype l 2>/dev/null
```

### How to use it

1.  **Create the file:**
    ```bash
    nano find_broken_links.sh
    ```
    Paste the code above into the file and save it (Ctrl+O, Enter, Ctrl+X).

2.  **Make it executable:**
    ```bash
    chmod +x find_broken_links.sh
    ```

3.  **Run it:**
    ```bash
    ./find_broken_links.sh
    ```
"""


def _strip_indent(line: str, indent: str) -> str:
    if not indent:
        return line
    if line.startswith(indent):
        return line[len(indent) :]
    n = 0
    while n < len(indent) and n < len(line) and line[n] in " \t":
        n += 1
    return line[n:]


def extract_fences(raw: str) -> tuple[str, list[tuple[str, str]]]:
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    fences: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        open_m = OPEN_RE.match(lines[i])
        if not open_m:
            out.append(lines[i])
            i += 1
            continue
        indent, marker, lang, rest = (
            open_m.group(1),
            open_m.group(2),
            open_m.group(3) or "",
            open_m.group(4) or "",
        )
        fence_char = marker[0]
        close_same = re.search(
            r"`{3,}[ \t]*$" if fence_char == "`" else r"~{3,}[ \t]*$",
            rest,
        )
        if close_same and rest[: close_same.start()].strip():
            fences.append((lang, rest[: close_same.start()].strip()))
            out.append(f"{indent}@@CODE{len(fences) - 1}@@")
            i += 1
            continue
        if fence_char in rest:
            out.append(lines[i])
            i += 1
            continue
        body: list[str] = []
        i += 1
        close_re = re.compile(rf"^\s*{re.escape(fence_char)}{{{len(marker)},}}[ \t]*$")
        while i < len(lines) and not close_re.match(lines[i]):
            body.append(_strip_indent(lines[i], indent))
            i += 1
        fences.append((lang, "\n".join(body)))
        out.append(f"{indent}@@CODE{len(fences) - 1}@@")
        if i < len(lines):
            i += 1
    return "\n".join(out), fences


class UiMarkdownFenceTests(unittest.TestCase):
    def test_utils_js_allows_indented_fences(self):
        src = UTILS_JS.read_text()
        self.assertIn(r"^(\s*)(`{3,}|~{3,})[ \t]*([\w+-]*)(.*)$", src)
        self.assertIn("stripFenceIndent", src)
        self.assertIn("isFenceToken(raw)", src)
        self.assertNotIn(r"^```([\w+-]*)[ \t]*$", src)

    def test_column_zero_fence_still_extracts(self):
        text, fences = extract_fences("```bash\necho hi\n```\n")
        self.assertEqual(len(fences), 1)
        self.assertEqual(fences[0], ("bash", "echo hi"))
        self.assertIn("@@CODE0@@", text)
        self.assertNotIn("```", text)

    def test_numbered_how_to_fences_are_code_blocks(self):
        text, fences = extract_fences(SAMPLE)
        self.assertEqual(len(fences), 4)
        self.assertEqual([lang for lang, _ in fences], ["bash"] * 4)
        self.assertEqual(fences[1][1], "nano find_broken_links.sh")
        self.assertEqual(fences[2][1], "chmod +x find_broken_links.sh")
        self.assertEqual(fences[3][1], "./find_broken_links.sh")
        self.assertNotIn("```", text)
        self.assertIn("    @@CODE1@@", text)
        self.assertIn("Paste the code above", text)

    def test_one_line_fence(self):
        _, fences = extract_fences("```bash chmod +x find_broken_links.sh ```")
        self.assertEqual(fences, [("bash", "chmod +x find_broken_links.sh")])

    def test_crlf_openers(self):
        _, fences = extract_fences("```python\r\nprint(1)\r\n```\r\n")
        self.assertEqual(fences, [("python", "print(1)")])


if __name__ == "__main__":
    unittest.main()

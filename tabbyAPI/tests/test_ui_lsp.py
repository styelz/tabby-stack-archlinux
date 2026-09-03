"""Code-mode LSP suffix map and in-container language servers."""

from __future__ import annotations

import unittest

from ui import lsp


class LspMapTests(unittest.TestCase):
    def test_suffix_to_language(self):
        self.assertEqual(lsp.language_for("app.py"), "python")
        self.assertEqual(lsp.language_for("src/main.ts"), "typescript")
        self.assertEqual(lsp.language_for("index.html"), "html")
        self.assertEqual(lsp.language_for("styles.css"), "css")
        self.assertEqual(lsp.language_for("data.json"), "json")
        self.assertEqual(lsp.language_for("readme.md"), "")

    def test_container_server_argv(self):
        self.assertEqual(lsp.command_for("python"), ["pylsp"])
        self.assertEqual(
            lsp.command_for("javascript"),
            ["typescript-language-server", "--stdio"],
        )
        self.assertIsNone(lsp.command_for("markdown"))

    def test_work_uri_roundtrip(self):
        self.assertEqual(lsp.file_uri("src/app.py"), "file:///work/src/app.py")
        self.assertEqual(lsp.uri_to_rel("file:///work/src/app.py"), "src/app.py")
        self.assertEqual(lsp.uri_to_rel("file:///etc/passwd"), "")

    def test_probe_without_server_is_unavailable(self):
        import asyncio

        reply = asyncio.run(lsp.handle_client("u", "c", {"type": "probe", "path": "readme.md"}))
        self.assertEqual(reply["type"], "probe")
        self.assertFalse(reply["available"])
        self.assertEqual(reply["language"], "")

    def test_probe_python_is_available(self):
        import asyncio

        reply = asyncio.run(lsp.handle_client("u", "c", {"type": "probe", "path": "a.py"}))
        self.assertEqual(reply["type"], "probe")
        self.assertTrue(reply["available"])
        self.assertEqual(reply["language"], "python")
        self.assertEqual(reply["command"], "pylsp")

    def test_as_int_ignores_bad_values(self):
        self.assertEqual(lsp._as_int(None, 1), 1)
        self.assertEqual(lsp._as_int("3", 0), 3)
        self.assertEqual(lsp._as_int({}, 2), 2)
        self.assertEqual(lsp._as_int(["x"], 0), 0)


if __name__ == "__main__":
    unittest.main()

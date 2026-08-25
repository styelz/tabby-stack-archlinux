"""Code-mode LSP suffix map and quiet skip when no server is on PATH."""

from __future__ import annotations

import unittest
from unittest import mock

from ui import lsp


class LspMapTests(unittest.TestCase):
    def test_suffix_to_language(self):
        self.assertEqual(lsp.language_for("app.py"), "python")
        self.assertEqual(lsp.language_for("src/main.ts"), "typescript")
        self.assertEqual(lsp.language_for("index.html"), "html")
        self.assertEqual(lsp.language_for("styles.css"), "css")
        self.assertEqual(lsp.language_for("data.json"), "json")
        self.assertEqual(lsp.language_for("readme.md"), "")

    def test_missing_server_is_none(self):
        with mock.patch("ui.lsp.shutil.which", return_value=None):
            self.assertIsNone(lsp.command_for("python"))
            self.assertIsNone(lsp.command_for("javascript"))

    def test_picks_first_server_on_path(self):
        def which(name, path=None):
            return "/usr/bin/pylsp" if name == "pylsp" else None

        with mock.patch("ui.lsp.shutil.which", side_effect=which):
            self.assertEqual(lsp.command_for("python"), ["/usr/bin/pylsp"])

    def test_probe_without_server_is_unavailable(self):
        with mock.patch("ui.lsp.shutil.which", return_value=None):
            # handle_client is async; probe does not spawn.
            import asyncio

            reply = asyncio.run(lsp.handle_client("u", "c", {"type": "probe", "path": "a.py"}))
        self.assertEqual(reply["type"], "probe")
        self.assertFalse(reply["available"])
        self.assertEqual(reply["language"], "python")


if __name__ == "__main__":
    unittest.main()

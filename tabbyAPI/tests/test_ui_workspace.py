"""Jailed UI Code-mode project folders."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ui import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        workspace.set_workspaces_dir(self.root)

    def tearDown(self):
        workspace.set_workspaces_dir(None)
        self._tmp.cleanup()

    def test_rejects_dotdot_and_absolute_paths(self):
        with self.assertRaises(ValueError):
            workspace.write_text("u", "c", "../x.txt", "no")
        with self.assertRaises(ValueError):
            workspace.write_text("u", "c", "/tmp/x.txt", "no")

    def test_write_replace_and_rename_keeps_history(self):
        workspace.write_text("u", "c", "a.txt", "one")
        workspace.write_text("u", "c", "a.txt", "two")
        workspace.str_replace("u", "c", "a.txt", "two", "three")
        self.assertEqual(workspace.read_text("u", "c", "a.txt"), "three")
        workspace.rename_file("u", "c", "a.txt", "b.txt")
        self.assertEqual(workspace.read_text("u", "c", "b.txt"), "three")
        versions = workspace.list_history("u", "c", "b.txt")
        self.assertTrue(versions)

    def test_delete_cleans_empty_parents(self):
        workspace.write_text("u", "c", "css/a.css", "x")
        workspace.delete_file("u", "c", "css/a.css")
        root = workspace.workspace_root("u", "c")
        self.assertFalse((root / "css").exists())

    def test_rename_and_delete_prefix(self):
        workspace.write_text("u", "c", "css/a.css", "a")
        workspace.write_text("u", "c", "css/b.css", "b")
        moved = workspace.rename_prefix("u", "c", "css", "styles")
        self.assertEqual({dst for _src, dst in moved}, {"styles/a.css", "styles/b.css"})
        deleted = workspace.delete_prefix("u", "c", "styles")
        self.assertEqual(set(deleted), {"styles/a.css", "styles/b.css"})
        self.assertEqual(workspace.list_files("u", "c"), [])

    def test_caps_limit_file_count(self):
        with mock.patch.object(workspace, "MAX_FILES", 2):
            workspace.write_text("u", "c", "a.txt", "1")
            workspace.write_text("u", "c", "b.txt", "2")
            with self.assertRaises(ValueError):
                workspace.write_text("u", "c", "c.txt", "3")


if __name__ == "__main__":
    unittest.main()

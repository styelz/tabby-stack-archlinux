"""UI Code-mode tool dispatch."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ui import code_agent, workspace


class CodeAgentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        workspace.set_workspaces_dir(Path(self._tmp.name))

    def tearDown(self):
        workspace.set_workspaces_dir(None)
        self._tmp.cleanup()

    def test_kind_aliases(self):
        self.assertEqual(code_agent._kind("write_file"), "write")
        self.assertEqual(code_agent._kind("search_replace"), "replace")
        self.assertEqual(code_agent._kind("rename_file"), "rename")
        self.assertEqual(code_agent._kind("delete_file"), "delete")
        self.assertEqual(code_agent._kind("optimize_image"), "optimize")

    def test_write_rename_delete(self):
        label, text = code_agent.execute_tool("u", "c", "Write", {"path": "a.txt", "contents": "hi"})
        self.assertTrue(label.startswith("Writing"))
        self.assertIn("a.txt", text)
        label, text = code_agent.execute_tool("u", "c", "Rename", {"path": "a.txt", "to": "b.txt"})
        self.assertTrue(label.startswith("Renaming"))
        self.assertEqual(workspace.read_text("u", "c", "b.txt"), "hi")
        label, text = code_agent.execute_tool("u", "c", "Delete", {"path": "b.txt"})
        self.assertTrue(label.startswith("Deleting"))
        self.assertEqual(workspace.list_files("u", "c"), [])

    def test_unknown_tool(self):
        label, text = code_agent.execute_tool("u", "c", "Shell", {"path": "a.txt"})
        self.assertEqual(label, "Tool error")
        self.assertIn("Unknown tool", text)


if __name__ == "__main__":
    unittest.main()

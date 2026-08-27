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
        self.assertEqual(code_agent._kind("run_command"), "shell")

    def test_optimize_image_schema_has_trim_border(self):
        specs = code_agent.code_tool_specs("agent")
        optimize = next(spec for spec in specs if spec.function.name == "OptimizeImage")
        params = optimize.function.parameters
        props = params["properties"] if isinstance(params, dict) else params.get("properties")
        self.assertIn("trim_border", props)

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
        label, text = code_agent.execute_tool("u", "c", "Nope", {"path": "a.txt"})
        self.assertEqual(label, "Tool error")
        self.assertIn("Unknown tool", text)

    def test_plan_preamble_is_not_complete(self):
        self.assertFalse(
            code_agent.plan_looks_complete(
                "I have read the project directory. It is empty. "
                "I will now design a comprehensive plan for the space travel "
                "company website."
            )
        )

    def test_plan_with_headings_is_complete(self):
        text = (
            "## Goal\n"
            "Build a space-travel marketing site.\n\n"
            "## Files\n"
            "- index.html — page shell and sections\n"
            "- styles.css — layout and theme\n"
            "- app.js — nav and starfield\n\n"
            "## Steps\n"
            "1. Write index.html with hero, packages, and booking form.\n"
            "2. Add styles.css for a dark space theme.\n"
            "3. Add app.js for the canvas starfield.\n\n"
            "## Assets\n"
            "- images/logo.png — qwen-image logo\n"
            "- images/hero.png — Flux nebula photograph\n\n"
            "## Risks\n"
            "Readable logo text needs Qwen-Image, not Flux."
        )
        self.assertTrue(code_agent.plan_looks_complete(text))

    def test_attach_plan_contract_once(self):
        messages = [{"role": "user", "content": "design a site"}]
        code_agent.attach_plan_user_contract(messages)
        code_agent.attach_plan_user_contract(messages)
        self.assertEqual(messages[0]["content"].count(code_agent.PLAN_CONTRACT_MARK), 1)
        self.assertTrue(messages[0]["content"].startswith("design a site"))

    def test_ask_and_plan_tools_are_read_only(self):
        for kind in ("ask", "plan"):
            names = {spec.function.name for spec in code_agent.code_tool_specs(kind)}
            self.assertEqual(names, {"Read", "List"})
        agent_names = {spec.function.name for spec in code_agent.code_tool_specs("agent")}
        self.assertIn("Write", agent_names)
        self.assertIn("Shell", agent_names)

    def test_ask_and_plan_refuse_writes(self):
        for kind in ("ask", "plan"):
            label, text = code_agent.execute_tool(
                "u", "c", "Write", {"path": "a.txt", "contents": "no"}, agent=kind
            )
            self.assertEqual(label, "Tool error")
            self.assertIn("read-only", text.lower())
        self.assertEqual(workspace.list_files("u", "c"), [])

    def test_system_prompt_follows_agent(self):
        ask = code_agent.code_system_for("u", "c", "ask")
        plan = code_agent.code_system_for("u", "c", "plan")
        agent = code_agent.code_system_for("u", "c", "agent")
        self.assertIn("earlier Plan or Ask", ask)
        self.assertIn("conversation and the project", ask)
        self.assertIn("revise that plan", plan)
        self.assertIn("<approved_plan>", agent)

    def test_attach_plan_contract_skips_build(self):
        quoted = (
            f"{code_agent.BUILD_PROMPT}\n\n<approved_plan>\n"
            "## Goal\nShip it.\n</approved_plan>"
        )
        messages = [{"role": "user", "content": quoted}]
        code_agent.attach_plan_user_contract(messages)
        self.assertEqual(messages[0]["content"], quoted)
        self.assertFalse(code_agent.is_build_prompt("design a site"))
        self.assertTrue(code_agent.is_build_prompt(quoted))


if __name__ == "__main__":
    unittest.main()

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

    def test_truncate_step_text(self):
        short = "hello"
        self.assertEqual(code_agent.truncate_step_text(short), short)
        long = "x" * (code_agent.MAX_STEP_RESULT + 20)
        out = code_agent.truncate_step_text(long)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), code_agent.MAX_STEP_RESULT + 1)

    def test_tool_step_payload_truncates_read_result(self):
        body = "line\n" * 200
        step = code_agent.tool_step_payload(
            "Read",
            {"path": "index.html", "contents": "ignored"},
            "Reading index.html",
            body,
        )
        self.assertEqual(step["type"], "tool")
        self.assertEqual(step["name"], "Read")
        self.assertEqual(step["args"], {"path": "index.html"})
        self.assertNotIn("contents", step["args"])
        self.assertTrue(step["result"].endswith("…"))
        self.assertLessEqual(len(step["result"]), code_agent.MAX_STEP_RESULT + 1)

    def test_tool_step_args_keep_path_and_command(self):
        step = code_agent.tool_step_payload(
            "Shell",
            {"command": "python3 -m http.server --help"},
            "Running command",
            "usage: ...",
        )
        self.assertEqual(step["args"]["command"], "python3 -m http.server --help")
        self.assertNotIn("path", step["args"])

    def test_remaining_stream_text(self):
        self.assertEqual(code_agent.remaining_stream_text("abc", "abc"), "")
        self.assertEqual(code_agent.remaining_stream_text("abcdef", "abc"), "def")
        self.assertEqual(code_agent.remaining_stream_text("pics", "wrote"), "pics")
        self.assertEqual(code_agent.remaining_stream_text("only", ""), "only")

    def test_parse_completion_chunk(self):
        self.assertIsNone(code_agent.parse_completion_chunk("[DONE]"))
        parsed = code_agent.parse_completion_chunk(
            '{"choices":[{"delta":{"content":"hi"}}]}'
        )
        self.assertEqual(parsed["choices"][0]["delta"]["content"], "hi")

    def test_message_from_stream_tool_calls(self):
        message = code_agent.message_from_stream(
            "ok",
            "think",
            [
                {
                    "id": "call_1",
                    "index": 0,
                    "function": {"name": "Write", "arguments": '{"path":"a.html"}'},
                }
            ],
        )
        self.assertEqual(message.content, "ok")
        self.assertEqual(message.reasoning_content, "think")
        pairs = code_agent._tool_pairs(message)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], "Write")
        self.assertEqual(pairs[0][1]["path"], "a.html")

    def test_format_agent_step_comment(self):
        comment = code_agent.format_agent_step_comment({"type": "demote"})
        self.assertTrue(comment.startswith(code_agent.AGENT_STEP_MARK))
        self.assertIn('"type":"demote"', comment)

    def test_sse_for_code_event_shapes(self):
        from endpoints.OAI.types.chat_completion import ChatCompletionRequest
        from sse_starlette import ServerSentEvent

        data = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}])
        status = code_agent.sse_for_code_event(
            ("status", "Writing index.html"),
            data,
            chunk_id="chatcmpl-x",
            created=1,
        )
        self.assertEqual(len(status), 1)
        self.assertIsInstance(status[0], ServerSentEvent)
        self.assertIn("Writing index.html", status[0].comment)
        content = code_agent.sse_for_code_event(
            ("content", "hello"),
            data,
            chunk_id="chatcmpl-x",
            created=1,
        )
        self.assertEqual(len(content), 1)
        self.assertIn("hello", content[0])
        self.assertIn("content", content[0])
        tool = code_agent.sse_for_code_event(
            ("tool", {"type": "tool", "name": "Read", "label": "Reading a.py"}),
            data,
            chunk_id="chatcmpl-x",
            created=1,
        )
        self.assertIn(code_agent.AGENT_STEP_MARK, tool[0].comment)


if __name__ == "__main__":
    unittest.main()

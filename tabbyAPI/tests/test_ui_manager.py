import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from ui import manager


class UiManagerTests(unittest.TestCase):
    def test_journalctl_cmd_follows_user_units(self):
        cmd = manager.journalctl_cmd(follow=True, lines=0)
        self.assertEqual(cmd[0], "journalctl")
        self.assertIn("--user", cmd)
        self.assertIn("-f", cmd)
        self.assertIn("--since", cmd)
        self.assertIn("now", cmd)
        self.assertNotIn("-n", cmd)
        self.assertIn("tabbyapi", cmd)
        self.assertIn("comfyui", cmd)

    def test_journalctl_cmd_history_still_uses_line_count(self):
        cmd = manager.journalctl_cmd(follow=False, lines=300)
        self.assertIn("-n", cmd)
        self.assertEqual(cmd[cmd.index("-n") + 1], "300")
        self.assertNotIn("-f", cmd)

    def test_ui_access_lines_are_detected(self):
        self.assertTrue(
            manager.is_ui_access_line(
                "2026-08-24T04:50:18+10:00 archy.local python[106135]: "
                "2026-08-24 04:50:18.835 INFO:     36.255.114.172:0 - "
                '"GET /v1/ui/assets/status.js HTTP/1.1" 200'
            )
        )
        self.assertTrue(
            manager.is_ui_access_line(
                "Aug 24 06:08:12 archy.local python[122943]: "
                "2026-08-24 06:08:12.392 INFO:     36.255.114.172:0 - "
                '"GET /v1/ui/status HTTP/1.1" 200'
            )
        )
        self.assertTrue(manager.is_ui_access_line('"POST /v1/ui/restart HTTP/1.1" 200'))
        self.assertTrue(manager.is_ui_access_line('"GET /v1/ui/logs/history?lines=300 HTTP/1.1" 200'))
        self.assertTrue(manager.is_ui_access_line('"GET /ui/status HTTP/1.1" 200'))
        self.assertTrue(manager.is_ui_access_line('"GET /openai/v1/ui/status HTTP/1.1" 200'))
        self.assertFalse(manager.is_ui_access_line('"GET /v1/chat/completions HTTP/1.1" 200'))
        self.assertFalse(manager.is_ui_access_line('"GET /health HTTP/1.1" 200'))
        self.assertFalse(manager.is_ui_access_line("Model loaded: qwen"))
        self.assertFalse(
            manager.is_ui_access_line("Management UI: http://127.0.0.1:5000/v1/ui")
        )

    def test_journalctl_history_drops_ui_access(self):
        previous = list(manager.PROCESS_LOGS)
        mixed = [
            "keep me",
            '"GET /v1/ui/status HTTP/1.1" 200',
            "also keep",
        ]
        try:
            with mock.patch.object(manager.shutil, "which", return_value=None):
                manager.PROCESS_LOGS.clear()
                manager.PROCESS_LOGS.extend(mixed)
                lines = manager.journalctl_history(10)
            self.assertEqual(lines, ["keep me", "also keep"])
        finally:
            manager.PROCESS_LOGS.clear()
            manager.PROCESS_LOGS.extend(previous)

    def test_journalctl_history_overfetches_then_filters(self):
        ui = '"GET /v1/ui/status HTTP/1.1" 200'
        stdout = "\n".join([ui, "real log", ui, "another"])
        completed = mock.Mock(returncode=0, stdout=stdout)
        with mock.patch.object(manager.shutil, "which", return_value="/usr/bin/journalctl"):
            with mock.patch.object(manager.subprocess, "run", return_value=completed) as run:
                lines = manager.journalctl_history(2)
        self.assertEqual(lines, ["real log", "another"])
        cmd = run.call_args[0][0]
        self.assertGreater(int(cmd[cmd.index("-n") + 1]), 2)

    def test_sanitize_chat_strips_tools_and_injects_system(self):
        payload = manager.sanitize_chat_payload(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "hello",
                        "tool_calls": [{"function": {"name": "Write"}}],
                    }
                ],
                "tools": [{"function": {"name": "Write"}}],
                "stream": True,
            }
        )
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("do not write", payload["messages"][0]["content"].lower())
        self.assertEqual(payload["messages"][-1]["content"], "hello")
        self.assertNotIn("tool_calls", payload["messages"][-1])

    def test_sanitize_rejects_empty_messages(self):
        with self.assertRaises(ValueError):
            manager.sanitize_chat_payload({"messages": []})

    def test_update_missing_script(self):
        missing = Path("/tmp/does-not-exist-tabby-update.sh")
        with mock.patch.object(manager, "STACK_ROOT", missing.parent):
            with mock.patch.object(Path, "is_file", return_value=False):
                result = manager.start_stack_update()
        self.assertFalse(result["ok"])
        self.assertIn("update.sh", result["message"])

    def test_git_update_waits_and_returns_restart_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "update.sh").write_text("#!/bin/bash\nexit 0\n")

            def fake_run(cmd, **kwargs):
                (root / manager.UPDATE_PROMPT_NAME).write_text(
                    json.dumps(
                        {
                            "title": "Restart API?",
                            "text": (
                                "The pull changed API code. Restart tabbyapi now so it loads "
                                "(about 65 seconds)?\n\n  tabbyAPI/foo.py"
                            ),
                            "summary": "Pulled the latest code.",
                            "pulled": True,
                            "yes_label": "Restart",
                            "no_label": "Skip",
                        }
                    )
                )
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(manager, "STACK_ROOT", root):
                with mock.patch.object(manager.subprocess, "run", side_effect=fake_run) as run:
                    with mock.patch.object(manager.subprocess, "Popen") as popen:
                        result = manager.start_stack_update(full=False)
            popen.assert_not_called()
            self.assertEqual(run.call_args[0][0][2:], ["--git", "--no-restart"])
            self.assertTrue(result["ok"])
            self.assertTrue(result["ask_restart"])
            self.assertEqual(result["restart_title"], "Restart API?")
            self.assertIn("tabbyAPI/foo.py", result["restart_text"])
            self.assertEqual(result["restart_yes"], "Restart")
            self.assertEqual(result["restart_no"], "Skip")
            self.assertEqual(result["message"], "Pulled the latest code.")

    def test_full_update_still_starts_in_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "update.sh").write_text("#!/bin/bash\nexit 0\n")
            with mock.patch.object(manager, "STACK_ROOT", root):
                with mock.patch.object(manager.subprocess, "Popen") as popen:
                    result = manager.start_stack_update(full=True)
            popen.assert_called_once()
            self.assertIn("--all", popen.call_args[0][0])
            self.assertTrue(result["ok"])
            self.assertNotIn("ask_restart", result)

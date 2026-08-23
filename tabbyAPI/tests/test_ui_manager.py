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
        self.assertIn("-n", cmd)
        self.assertIn("0", cmd)
        self.assertIn("tabbyapi", cmd)
        self.assertIn("comfyui", cmd)

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

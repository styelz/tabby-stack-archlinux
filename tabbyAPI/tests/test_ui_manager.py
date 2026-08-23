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

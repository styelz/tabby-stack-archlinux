import tempfile
import unittest
from pathlib import Path
from unittest import mock

import restart_stack
from common.phrase_switch import restart_reply_text, start_restart
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest


class RestartStackTests(unittest.TestCase):
    def test_restart_units_llm_stops_comfy(self):
        with mock.patch("restart_stack.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.assertEqual(restart_stack.restart_units("llm"), 0)
        cmds = [call.args[0] for call in run.call_args_list]
        self.assertEqual(cmds[0], ["systemctl", "--user", "stop", "comfyui"])
        self.assertEqual(cmds[-1], ["systemctl", "--user", "restart", "tabbyapi"])

    def test_restart_units_comfy_restarts_both(self):
        with mock.patch("restart_stack.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            restart_stack.restart_units("comfy")
        cmds = [call.args[0] for call in run.call_args_list]
        self.assertEqual(cmds[0], ["systemctl", "--user", "reset-failed", "comfyui"])
        self.assertEqual(cmds[1], ["systemctl", "--user", "restart", "comfyui"])
        self.assertEqual(cmds[-1], ["systemctl", "--user", "restart", "tabbyapi"])

    def test_main_unlinks_lock_after_delay(self):
        with tempfile.TemporaryDirectory() as raw:
            lock = Path(raw) / "switch-model.lock"
            lock.write_text("restart", encoding="utf-8")
            with (
                mock.patch("restart_stack.time.sleep") as sleep,
                mock.patch("restart_stack.restart_units", return_value=0) as units,
            ):
                self.assertEqual(
                    restart_stack.main(["--delay", "1.5", "--mode", "llm", "--lock", str(lock)]),
                    0,
                )
            sleep.assert_called_once_with(1.5)
            units.assert_called_once_with("llm")
            self.assertFalse(lock.exists())

    def test_start_restart_detaches_helper(self):
        with (
            mock.patch("common.phrase_switch.shutil.which", return_value="/usr/bin/systemctl"),
            mock.patch("common.phrase_switch.gpu_is_comfy", return_value=False),
            mock.patch("common.phrase_switch.subprocess.Popen") as popen,
            mock.patch("common.phrase_switch.LOCK") as lock,
            mock.patch("common.phrase_switch.LOG") as log,
        ):
            lock.write_text = mock.Mock()
            log.touch = mock.Mock()
            log.open = mock.mock_open()
            self.assertTrue(start_restart())
            popen.assert_called_once()
            args = popen.call_args.args[0]
            self.assertIn("restart_stack.py", args[1])
            self.assertIn("--mode", args)

    def test_start_restart_missing_systemctl(self):
        with mock.patch("common.phrase_switch.shutil.which", return_value=None):
            self.assertFalse(start_restart())

    def test_restart_reply_mentions_wait(self):
        data = ChatCompletionRequest(
            messages=[ChatCompletionMessage(role="user", content="restart")]
        )
        with mock.patch("common.phrase_switch.gpu_is_comfy", return_value=False):
            with mock.patch("common.phrase_switch.wait_hint", return_value="Wait about 65 seconds"):
                text = restart_reply_text()
        self.assertIn("Restarting the stack", text)
        self.assertIn("gpt-4o", text)
        self.assertIsNotNone(data)


if __name__ == "__main__":
    unittest.main()

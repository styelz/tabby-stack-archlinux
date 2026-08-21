import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.phrase_switch import (
    comfy_not_running_text,
    llm_loading_text,
    llm_not_ready_text,
    switch_reply_text,
)
from common.switch_times import format_duration, ready_seconds, wait_hint


SAMPLE = {
    "qwen": {"ready_s": 12},
    "qwen35": {"ready_s": 118},
    "qwen36": {"ready_s": 95},
    "comfy": {"ready_s": 6, "flux_s": 40, "qwen_image_s": 80},
    "llm": {"ready_s": 55},
}


class SwitchTimesTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(1), "1 second")
        self.assertEqual(format_duration(12), "10 seconds")
        self.assertEqual(format_duration(15), "15 seconds")
        self.assertEqual(format_duration(60), "60 seconds")
        self.assertEqual(format_duration(89), "90 seconds")
        self.assertEqual(format_duration(90), "2 minutes")
        self.assertEqual(format_duration(118), "2 minutes")
        self.assertEqual(format_duration(150), "2 minutes")

    def test_wait_hint_from_table(self):
        self.assertEqual(wait_hint("qwen", SAMPLE), "Wait about 10 seconds")
        self.assertEqual(wait_hint("qwen35", SAMPLE), "Wait about 2 minutes")
        self.assertEqual(wait_hint("flux", SAMPLE), "Wait about 5 seconds")
        self.assertEqual(wait_hint("unknown", SAMPLE), "Wait about 65 seconds")

    def test_ready_seconds_reads_file(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "switch_times.json"
            path.write_text(json.dumps(SAMPLE), encoding="utf-8")
            with mock.patch("common.switch_times.TIMES_PATH", path):
                self.assertEqual(ready_seconds("qwen35"), 118)
                self.assertEqual(wait_hint("comfy"), "Wait about 5 seconds")

    def test_switch_reply_uses_table(self):
        with mock.patch("common.phrase_switch.wait_hint", side_effect=lambda name: wait_hint(name, SAMPLE)):
            comfy = switch_reply_text("comfy")
            self.assertIn("Wait about 5 seconds", comfy)
            qwen35 = switch_reply_text("qwen35")
            self.assertIn("Wait about 2 minutes", qwen35)
            llm = switch_reply_text("llm")
            self.assertIn("Wait about 55 seconds", llm)

    def test_loading_and_not_ready_copy(self):
        with mock.patch("common.phrase_switch.wait_hint", side_effect=lambda name: wait_hint(name, SAMPLE)):
            with mock.patch("common.phrase_switch.ready_seconds", side_effect=lambda name: ready_seconds(name, SAMPLE)):
                with mock.patch("common.phrase_switch.format_duration", side_effect=format_duration):
                    with mock.patch("common.phrase_switch.gpu_label", return_value="12 GB"):
                        not_ready = llm_not_ready_text()
                        self.assertIn("wait about 10 seconds", not_ready)
                        self.assertIn("2 minutes", not_ready)
                        loading = llm_loading_text("qwen35")
                        self.assertIn("Wait about 2 minutes", loading)
                        self.assertIn("qwen35 on 12 GB", loading)
                        comfy = comfy_not_running_text()
                        self.assertIn("wait about 5 seconds", comfy)


if __name__ == "__main__":
    unittest.main()

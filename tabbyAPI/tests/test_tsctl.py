import importlib.util
import unittest
from pathlib import Path
from unittest import mock


def _load_tsctl():
    path = Path(__file__).resolve().parents[1] / "tools" / "tsctl.py"
    spec = importlib.util.spec_from_file_location("tsctl_cli", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TsctlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tsctl = _load_tsctl()

    def test_parse_pairs(self):
        self.assertEqual(self.tsctl.parse_pairs(["timeout=120"]), [("timeout", "120")])
        self.assertEqual(self.tsctl.parse_pairs(["timeout", "90"]), [("timeout", "90")])

    def test_dispatch_sets_screensaver_timeout(self):
        payload = {
            "ok": True,
            "tabby": [],
            "screensaver": {
                "name": "screensaver",
                "label": "Screensaver",
                "fields": [
                    {"name": "enabled", "kind": "bool", "value": False},
                    {"name": "timeout", "kind": "int", "value": 120},
                    {"name": "logout_timeout", "kind": "int", "value": 10},
                    {"name": "hud_timeout", "kind": "int", "value": 300},
                ],
            },
            "system": {"name": "system", "fields": []},
        }
        with mock.patch.object(self.tsctl, "load_settings", return_value=payload):
            with mock.patch.object(self.tsctl, "save_settings", return_value={"ok": True}) as save:
                code = self.tsctl.dispatch(["screensaver", "timeout=90"])
        self.assertEqual(code, 0)
        save.assert_called_once()
        self.assertEqual(save.call_args[0][0]["screensaver"]["timeout"], 90)

    def test_dispatch_enable(self):
        payload = {
            "ok": True,
            "tabby": [],
            "screensaver": {
                "name": "screensaver",
                "fields": [{"name": "enabled", "kind": "bool", "value": False}],
            },
            "system": {"name": "system", "fields": []},
        }
        with mock.patch.object(self.tsctl, "load_settings", return_value=payload):
            with mock.patch.object(self.tsctl, "save_settings", return_value={"ok": True}) as save:
                self.tsctl.dispatch(["screensaver", "enable"])
        self.assertEqual(save.call_args[0][0]["screensaver"]["enabled"], True)

    def test_complete_lists_sections(self):
        payload = {
            "tabby": [{"name": "network", "fields": [{"name": "host"}]}],
            "screensaver": {"name": "screensaver", "fields": [{"name": "timeout"}]},
            "system": {"name": "system", "fields": []},
        }
        with mock.patch.object(self.tsctl, "load_settings", return_value=payload):
            words = self.tsctl.complete_words(1, ["tsctl"])
        self.assertIn("screensaver", words)
        self.assertIn("network", words)
        with mock.patch.object(self.tsctl, "load_settings", return_value=payload):
            keys = self.tsctl.complete_words(2, ["tsctl", "screensaver"])
        self.assertIn("timeout", keys)
        self.assertIn("enable", keys)

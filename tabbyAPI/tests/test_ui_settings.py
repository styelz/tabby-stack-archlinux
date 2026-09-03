import unittest
from pathlib import Path
from unittest import mock

from ui import settings

SETTINGS_JS = Path(__file__).resolve().parents[1] / "ui" / "static" / "settings.js"


class UiSettingsSaveTests(unittest.TestCase):
    def test_reload_failure_returns_warning(self):
        with mock.patch.object(settings, "_apply_tabby"):
            with mock.patch.object(settings, "_reload_live", side_effect=RuntimeError("bad yaml")):
                with mock.patch.object(
                    settings,
                    "load_settings",
                    return_value={"ok": True, "tabby": [], "restart_hint": "hint"},
                ):
                    data = settings.save_settings({"tabby": {"logging": {}}})
        self.assertTrue(data["ok"])
        self.assertIn("bad yaml", data["reload_warning"])
        self.assertTrue(data["reload_warning"].startswith("Saved, but live reload failed:"))

    def test_reload_success_has_no_warning(self):
        with mock.patch.object(settings, "_apply_tabby"):
            with mock.patch.object(settings, "_reload_live"):
                with mock.patch.object(
                    settings,
                    "load_settings",
                    return_value={"ok": True, "tabby": [], "restart_hint": "hint"},
                ):
                    data = settings.save_settings({"tabby": {"logging": {}}})
        self.assertTrue(data["ok"])
        self.assertNotIn("reload_warning", data)


class SettingsJsTests(unittest.TestCase):
    def test_save_shows_reload_warning(self):
        src = SETTINGS_JS.read_text(encoding="utf-8")
        self.assertIn("data.reload_warning", src)
        self.assertIn("showError(data.reload_warning)", src)

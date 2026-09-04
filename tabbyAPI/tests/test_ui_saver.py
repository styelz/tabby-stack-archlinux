import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from ui import saver


def _load_kiosk():
    path = Path(__file__).resolve().parents[1] / "deploy/arch/tabby-saver.py"
    spec = importlib.util.spec_from_file_location("tabby_saver_kiosk", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _request(host: str | None, forwarded: str | None = None):
    client = None if host is None else SimpleNamespace(host=host)
    headers = {}
    if forwarded is not None:
        headers["x-forwarded-for"] = forwarded
    return SimpleNamespace(client=client, headers=headers)


class SaverLoopbackTests(unittest.TestCase):
    def test_loopback_peers_allowed(self):
        for host in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"):
            self.assertTrue(saver.peer_is_loopback(_request(host)), host)

    def test_lan_peer_rejected(self):
        self.assertFalse(saver.peer_is_loopback(_request("192.168.1.20")))
        self.assertFalse(saver.peer_is_loopback(_request("10.0.0.8")))

    def test_local_proxy_with_public_forwarded_rejected(self):
        self.assertFalse(saver.peer_is_loopback(_request("127.0.0.1", "203.0.113.9")))

    def test_missing_client_rejected(self):
        self.assertFalse(saver.peer_is_loopback(_request(None)))

    def test_require_loopback_raises(self):
        with self.assertRaises(HTTPException) as caught:
            saver.require_loopback(_request("8.8.8.8"))
        self.assertEqual(caught.exception.status_code, 403)


class SaverSanitizeTests(unittest.IsolatedAsyncioTestCase):
    def test_strips_prompts_users_and_job_text(self):
        raw = {
            "ok": True,
            "gpu_mode": "llm",
            "profile": "qwen",
            "busy": True,
            "switching": False,
            "restarting": False,
            "user": "alice",
            "api_base": "https://example.invalid/v1",
            "job": {"prompt": "secret image prompt", "phase": "rendering"},
            "gpu": {
                "name": "RTX 4070 Ti",
                "memory_used_mib": 7100,
                "memory_total_mib": 12282,
                "utilization_pct": 82,
                "temperature_c": 64,
            },
            "host": {"cpu_pct": 12.3, "ram_pct": 40.0, "load1": 1.1},
            "stack_queue": {
                "busy": True,
                "kind": "chat",
                "occupant": "alice",
                "prompt": "how do I hack",
                "chat_id": "abc123",
                "hint": "alice is chatting.",
            },
        }
        payload = saver.sanitize_status(raw)
        blob = repr(payload)
        self.assertNotIn("alice", blob)
        self.assertNotIn("secret", blob)
        self.assertNotIn("hack", blob)
        self.assertNotIn("abc123", blob)
        self.assertNotIn("example.invalid", blob)
        self.assertEqual(payload["gpu_mode"], "llm")
        self.assertEqual(payload["profile"], "qwen")
        self.assertTrue(payload["busy"])
        self.assertEqual(payload["kind"], "chat")
        self.assertEqual(payload["gpu"]["utilization_pct"], 82)
        self.assertEqual(payload["gpu"]["vram_pct"], 58)
        self.assertEqual(payload["gpu"]["temperature_c"], 64)
        self.assertEqual(payload["host"]["cpu_pct"], 12.3)
        for key in ("occupant", "prompt", "chat_id", "user", "hint", "job", "stack_queue"):
            self.assertNotIn(key, payload)

    def test_unknown_kind_dropped(self):
        payload = saver.sanitize_status(
            {
                "gpu_mode": "llm",
                "stack_queue": {"kind": "admin-shell", "busy": True, "prompt": "nope"},
            }
        )
        self.assertIsNone(payload["kind"])
        self.assertTrue(payload["busy"])

    def test_idle_defaults(self):
        payload = saver.sanitize_status({})
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["busy"])
        self.assertFalse(payload["switching"])
        self.assertIsNone(payload["kind"])
        self.assertIsNone(payload["gpu"]["vram_pct"])

    async def test_saver_state_uses_empty_username(self):
        leaked = {
            "gpu_mode": "comfy",
            "profile": "flux",
            "busy": False,
            "switching": True,
            "restarting": False,
            "gpu": {
                "utilization_pct": 10,
                "memory_used_mib": 100,
                "memory_total_mib": 200,
            },
            "host": {"cpu_pct": 1},
            "stack_queue": {"busy": False, "kind": "gpu", "occupant": "bob"},
        }
        mocked = mock.AsyncMock(return_value=leaked)
        with mock.patch("ui.manager.stack_status", new=mocked) as status:
            payload = await saver.saver_state()
        status.assert_awaited_once()
        kwargs = status.await_args.kwargs
        self.assertEqual(kwargs.get("username"), "")
        self.assertIsNone(kwargs.get("request"))
        self.assertEqual(payload["kind"], "gpu")
        self.assertTrue(payload["switching"])
        self.assertNotIn("bob", repr(payload))


class SaverKioskSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kiosk = _load_kiosk()

    def test_idle_uses_slow_idle_palette(self):
        scene = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "profile": "qwen", "busy": False, "gpu": {"utilization_pct": 3}},
            True,
        )
        self.assertEqual(scene["phase"], "idle")
        self.assertEqual(scene["palette"], "idle")
        self.assertFalse(scene["live"])

    def test_chat_busy_is_generating(self):
        scene = self.kiosk.scene_from_state(
            {
                "gpu_mode": "llm",
                "kind": "chat",
                "busy": True,
                "gpu": {"utilization_pct": 80, "vram_pct": 70, "temperature_c": 64},
            },
            True,
        )
        self.assertEqual(scene["phase"], "generating")
        self.assertEqual(scene["palette"], "chat")
        self.assertTrue(scene["live"])
        self.assertGreater(scene["speed"], 0.2)

    def test_comfy_and_switch_palettes(self):
        image = self.kiosk.scene_from_state(
            {"gpu_mode": "comfy", "kind": "image", "busy": True}, True
        )
        switch = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "switching": True, "kind": "gpu"}, True
        )
        waiting = self.kiosk.scene_from_state(None, False)
        self.assertEqual(image["palette"], "image")
        self.assertEqual(switch["palette"], "switch")
        self.assertEqual(waiting["phase"], "waiting for api")

    def test_saver_url_joins_origin(self):
        self.assertEqual(
            self.kiosk.saver_url("http://127.0.0.1:5000/"),
            "http://127.0.0.1:5000/v1/ui/saver/state",
        )

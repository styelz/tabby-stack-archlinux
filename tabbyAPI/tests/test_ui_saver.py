import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from common import live_decode
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


class _FakeScreen:
    def __init__(self) -> None:
        self.blits: list[tuple] = []

    def get_size(self) -> tuple[int, int]:
        return (1280, 720)

    def blit(self, *args: object) -> None:
        self.blits.append(args)


class _FakeFont:
    def size(self, text: str) -> tuple[int, int]:
        return (len(text) * 8, 16)

    def render(self, text: str, _aa: bool, _color: object) -> str:
        return text


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
            "tokens": 12,
            "stage": "decode",
            "waiters": 2,
            "elapsed_s": 9,
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
        self.assertEqual(payload["tokens"], 12)
        self.assertEqual(payload["stage"], "decode")
        self.assertEqual(payload["waiters"], 2)
        self.assertEqual(payload["elapsed_s"], 9)
        self.assertEqual(payload["image_n"], None)
        self.assertEqual(payload["image_of"], None)
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
        self.assertEqual(payload["stage"], "idle")
        self.assertEqual(payload["tokens"], 0)

    def test_idle_defaults(self):
        payload = saver.sanitize_status({})
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["busy"])
        self.assertFalse(payload["switching"])
        self.assertIsNone(payload["kind"])
        self.assertIsNone(payload["gpu"]["vram_pct"])
        self.assertEqual(payload["stage"], "idle")
        self.assertEqual(payload["tokens"], 0)
        self.assertEqual(payload["waiters"], 0)
        self.assertIsNone(payload["image_n"])

    def test_unknown_stage_becomes_idle(self):
        payload = saver.sanitize_status({"stage": "secret-thoughts", "tokens": -3})
        self.assertEqual(payload["stage"], "idle")
        self.assertEqual(payload["tokens"], 0)

    def test_queue_live_without_busy_flag_is_still_busy(self):
        payload = saver.sanitize_status(
            {"gpu_mode": "llm", "stack_queue": {"busy": False, "live": True, "kind": "chat"}}
        )
        self.assertTrue(payload["busy"])
        self.assertEqual(payload["kind"], "chat")

    async def test_saver_state_uses_empty_username(self):
        snap = mock.Mock(
            return_value={"busy": False, "kind": "gpu", "occupant": "bob", "live": False}
        )
        with (
            mock.patch("ui.occupancy.snapshot", snap),
            mock.patch("ui.manager.stack_status", new=mock.AsyncMock()) as status,
            mock.patch("ui.manager.cached_nvidia_stats", return_value={}),
            mock.patch("ui.manager.ensure_gpu_cache"),
            mock.patch("common.live_decode.snapshot", return_value={"tokens": 0, "stage": "idle"}),
            mock.patch("images.jobs.active_mcp_image_job", return_value=None),
            mock.patch("ui.flight.iter_live_flights", return_value=[]),
            mock.patch("common.phrase_switch.switch_lock_held", return_value=True),
            mock.patch("common.phrase_switch.switch_lock_name", return_value="comfy"),
            mock.patch("common.gpu_mode.read_mode", return_value={"mode": "comfy"}),
            mock.patch("images.jobs.loaded_tabby_name", return_value=None),
            mock.patch("common.phrase_switch.profile_alias_for_model", return_value=None),
            mock.patch("common.phrase_switch.last_llm_profile_name", return_value=""),
            mock.patch("select_model.last_profile", return_value="flux"),
        ):
            payload = await saver.saver_state()
        snap.assert_called_once_with("")
        status.assert_not_called()
        self.assertEqual(payload["kind"], "gpu")
        self.assertTrue(payload["switching"])
        self.assertEqual(payload["stage"], "switch")
        self.assertEqual(payload["profile"], "flux")
        self.assertIsNone(payload["gpu"]["utilization_pct"])
        self.assertNotIn("bob", repr(payload))


class SaverKioskSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kiosk = _load_kiosk()

    def test_high_gpu_util_alone_is_still_idle(self):
        scene = self.kiosk.scene_from_state(
            {
                "gpu_mode": "llm",
                "profile": "qwen",
                "busy": False,
                "kind": None,
                "gpu": {"utilization_pct": 41, "vram_pct": 70, "temperature_c": 55},
            },
            True,
        )
        self.assertEqual(scene["phase"], "idle")
        self.assertEqual(scene["palette"], "idle")
        self.assertFalse(scene["live"])

    def test_kind_without_a_job_is_idle(self):
        scene = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": False},
            True,
        )
        self.assertEqual(scene["phase"], "idle")
        self.assertFalse(scene["live"])

    def test_idle_uses_idle_palette_but_keeps_moving(self):
        scene = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "profile": "qwen", "busy": False, "gpu": {"utilization_pct": 3}},
            True,
        )
        self.assertEqual(scene["phase"], "idle")
        self.assertEqual(scene["palette"], "idle")
        self.assertFalse(scene["live"])
        self.assertGreaterEqual(scene["speed"], 0.30)
        self.assertLess(scene["speed"], 0.55)
        self.assertGreaterEqual(scene["intensity"], 0.45)

    def test_hud_only_when_live(self):
        idle = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "profile": "qwen", "busy": False},
            True,
        )
        hot = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": True, "profile": "qwen"},
            True,
        )
        idle_screen = _FakeScreen()
        hot_screen = _FakeScreen()
        font = _FakeFont()
        self.kiosk.draw_hud(idle_screen, font, font, idle)
        self.kiosk.draw_hud(hot_screen, font, font, hot)
        self.assertEqual(idle_screen.blits, [])
        self.assertGreater(len(hot_screen.blits), 0)

    def test_neurons_only_fire_when_live(self):
        idle = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "profile": "qwen", "busy": False},
            True,
        )
        hot = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": True, "profile": "qwen"},
            True,
        )
        self.assertIsNone(self.kiosk.neuron_overlay_state(idle))
        overlay = self.kiosk.neuron_overlay_state(hot)
        assert overlay is not None
        self.assertGreater(len(overlay["nodes"]), 20)
        self.assertGreater(len(overlay["edges"]), 20)
        self.assertGreater(len(overlay["pulses"]), 10)
        self.assertGreater(sum(overlay["fires"]), 0.5)
        xs = [p[0] for p in overlay["nodes"]]
        ys = [p[1] for p in overlay["nodes"]]
        self.assertLess(min(xs), 0.05)
        self.assertGreater(max(xs), 0.95)
        self.assertLess(min(ys), 0.05)
        self.assertGreater(max(ys), 0.95)
        ring, head = self.kiosk.neuron_draw_sizes(1.0, 1.0, 1080)
        self.assertLessEqual(ring, 16)
        self.assertLessEqual(head, 8)
        self.assertGreaterEqual(ring, 3)
        fading = dict(hot)
        fading["live"] = False
        fading["overlay"] = 0.4
        self.assertIsNotNone(self.kiosk.neuron_overlay_state(fading))
        gone = dict(hot)
        gone["live"] = False
        gone["overlay"] = 0.0
        self.assertIsNone(self.kiosk.neuron_overlay_state(gone))
        boot = dict(hot)
        boot["cycle"] = "boot"
        boot["cycle_t"] = 0.0
        boot["overlay"] = 0.08
        boot_state = self.kiosk.neuron_overlay_state(boot)
        self.assertIsNotNone(boot_state)
        halt = dict(hot)
        halt["live"] = False
        halt["cycle"] = "halt"
        halt["cycle_t"] = 0.2
        halt["overlay"] = 0.7
        self.assertIsNotNone(self.kiosk.neuron_overlay_state(halt))

    def test_neuron_pulses_travel_one_way(self):
        hot = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": True, "profile": "qwen"},
            True,
        )
        hot["st"] = 1.0
        first = self.kiosk.neuron_overlay_state(hot)
        hot["st"] = 1.05
        second = self.kiosk.neuron_overlay_state(hot)
        assert first is not None and second is not None
        u0 = first["pulses"][0][1]
        u1 = second["pulses"][0][1]
        self.assertNotEqual(u0, u1)

    def test_chat_busy_is_thinking_and_hot(self):
        scene = self.kiosk.scene_from_state(
            {
                "gpu_mode": "llm",
                "kind": "chat",
                "busy": True,
                "gpu": {"utilization_pct": 0, "vram_pct": 70, "temperature_c": 48},
            },
            True,
        )
        self.assertEqual(scene["phase"], "thinking")
        self.assertEqual(scene["palette"], "chat")
        self.assertTrue(scene["live"])
        self.assertGreaterEqual(scene["intensity"], 0.75)
        self.assertGreater(scene["speed"], 0.5)

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

    def test_follow_keeps_plasma_phase_when_speed_jumps(self):
        follow = self.kiosk.SceneFollow()
        idle = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "busy": False, "gpu": {"utilization_pct": 2}},
            True,
        )
        hot = self.kiosk.scene_from_state(
            {
                "gpu_mode": "llm",
                "kind": "chat",
                "busy": True,
                "gpu": {"utilization_pct": 90},
            },
            True,
        )
        a = follow.tick(idle, 0.04, 10.0)
        b = follow.tick(hot, 0.04, 10.04)
        self.assertGreaterEqual(b["st"], a["st"])
        self.assertLess(b["st"] - a["st"], 0.05)
        self.assertLess(abs(b["intensity"] - a["intensity"]), 0.08)
        self.assertEqual(b["cycle"], "boot")
        self.assertEqual(b["phase"], "gearing up")
        self.assertGreaterEqual(b["overlay"], 0.85)
        self.assertIsNotNone(self.kiosk.neuron_overlay_state(b))

    def test_follow_holds_live_through_a_brief_idle_poll(self):
        follow = self.kiosk.SceneFollow()
        hot = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": True, "gpu": {"utilization_pct": 80}},
            True,
        )
        idle = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "busy": False, "gpu": {"utilization_pct": 0}},
            True,
        )
        follow.tick(hot, 0.04, 1.0)
        held = follow.tick(idle, 0.04, 1.5)
        self.assertTrue(held["live"])
        later = follow.tick(idle, 0.04, 8.0)
        self.assertFalse(later["live"])
        self.assertIn(later["cycle"], ("halt", "idle"))

    def test_follow_reaches_hot_intensity_while_thinking(self):
        follow = self.kiosk.SceneFollow()
        hot = self.kiosk.scene_from_state(
            {
                "gpu_mode": "llm",
                "kind": "chat",
                "busy": True,
                "gpu": {"utilization_pct": 5},
            },
            True,
        )
        scene = None
        for step in range(40):
            scene = follow.tick(hot, 0.04, 1.0 + step * 0.04)
        self.assertEqual(scene["phase"], "thinking")
        self.assertGreater(scene["intensity"], 0.7)
        self.assertGreater(scene["weights"]["chat"], 0.8)

    def test_resume_on_idle_or_logout(self):
        resume = self.kiosk.should_resume_saver
        self.assertFalse(
            resume(
                now=10.0,
                last_input=9.0,
                idle_s=120.0,
                logout_idle_s=10.0,
                logged_in=False,
            )
        )
        self.assertTrue(
            resume(
                now=20.0,
                last_input=9.0,
                idle_s=120.0,
                logout_idle_s=10.0,
                logged_in=False,
            )
        )
        self.assertFalse(
            resume(
                now=11.0,
                last_input=10.5,
                idle_s=120.0,
                logout_idle_s=10.0,
                logged_in=False,
            )
        )
        self.assertFalse(
            resume(
                now=11.0,
                last_input=10.5,
                idle_s=120.0,
                logout_idle_s=10.0,
                logged_in=True,
            )
        )
        self.assertTrue(
            resume(
                now=140.0,
                last_input=10.5,
                idle_s=120.0,
                logout_idle_s=10.0,
                logged_in=True,
            )
        )

    def test_follow_fades_neuron_overlay(self):
        follow = self.kiosk.SceneFollow()
        hot = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": True},
            True,
        )
        idle = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "busy": False},
            True,
        )
        now = 10.0
        scene = follow.tick(hot, 0.04, now)
        for _step in range(80):
            now += 0.04
            scene = follow.tick(hot, 0.04, now)
        self.assertGreater(scene["overlay"], 0.9)
        after = now
        for _step in range(20):
            after += 0.04
            scene = follow.tick(idle, 0.04, after)
        self.assertEqual(scene["cycle"], "halt")
        self.assertEqual(scene["phase"], "gearing down")
        after += 6.0
        scene = follow.tick(idle, 0.04, after)
        for _step in range(90):
            after += 0.04
            scene = follow.tick(idle, 0.04, after)
        self.assertLess(scene["overlay"], 0.05)
        self.assertEqual(scene["cycle"], "idle")

    def test_login_from_ps_ignores_getty(self):
        self.assertFalse(self.kiosk.login_from_ps("agetty\nlogin\n"))
        self.assertTrue(self.kiosk.login_from_ps("agetty\nbash\n"))

    def test_tty_nr_and_evdev(self):
        self.assertEqual(self.kiosk.tty_nr("tty8"), 8)
        self.assertEqual(self.kiosk.tty_nr("/dev/tty1"), 1)
        self.assertTrue(self.kiosk.evdev_is_activity(self.kiosk.EV_KEY))
        self.assertFalse(self.kiosk.evdev_is_activity(0))

    def test_kiosk_key_dismisses_window_esc_quits(self):
        pygame = SimpleNamespace(
            QUIT=256,
            KEYDOWN=768,
            KEYUP=769,
            MOUSEMOTION=1024,
            K_ESCAPE=27,
            K_q=113,
        )
        key = SimpleNamespace(type=768, key=97)
        esc = SimpleNamespace(type=768, key=27)
        mouse = SimpleNamespace(type=1024, key=0)
        self.assertEqual(self.kiosk.is_dismiss_event(key, pygame, False), "dismiss")
        self.assertEqual(self.kiosk.is_dismiss_event(mouse, pygame, False), "dismiss")
        self.assertEqual(self.kiosk.is_dismiss_event(esc, pygame, True), "quit")
        self.assertIsNone(self.kiosk.is_dismiss_event(key, pygame, True))

    def test_parse_args_idle_default_is_two_minutes(self):
        args = self.kiosk.parse_args([])
        self.assertEqual(args.idle, 120.0)
        self.assertEqual(args.logout_idle, 10.0)
        self.assertEqual(args.poll, 0.1)
        self.assertEqual(args.width, 480)
        self.assertEqual(args.height, 270)
        args = self.kiosk.parse_args(
            ["--idle", "120", "--logout-idle", "10", "--user-tty", "tty1", "--saver-tty", "tty8"]
        )
        self.assertEqual(args.idle, 120.0)
        self.assertEqual(args.logout_idle, 10.0)
        self.assertEqual(args.user_tty, "tty1")
        self.assertEqual(args.saver_tty, "tty8")

    def test_hud_omits_zeros_when_gpu_cache_miss(self):
        hot = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": True, "profile": "qwen"},
            True,
        )
        self.assertFalse(hot["has_gpu"])
        screen = _FakeScreen()
        self.kiosk.draw_hud(screen, _FakeFont(), _FakeFont(), hot)
        text = " ".join(str(item) for item in screen.blits)
        self.assertNotIn("GPU 0%", text)
        self.assertNotIn("VRAM 0%", text)
        self.assertIn("thinking", text)

    def test_hud_type_is_large_with_a_halo(self):
        large, small = self.kiosk.hud_font_sizes(1080)
        self.assertGreaterEqual(large, 60)
        self.assertGreaterEqual(small, 44)
        self.assertGreater(large, small)
        halo = self.kiosk.hud_halo_offsets(3)
        self.assertGreaterEqual(len(halo), 8)
        self.assertNotIn((0, 0), halo)
        hot = self.kiosk.scene_from_state(
            {"gpu_mode": "llm", "kind": "chat", "busy": True, "profile": "qwen"},
            True,
        )
        screen = _FakeScreen()
        self.kiosk.draw_hud(screen, _FakeFont(), _FakeFont(), hot)
        phase_blits = sum(1 for item in screen.blits if item and item[0] == "thinking")
        self.assertGreaterEqual(phase_blits, 9)

    def test_decode_token_ticks_raise_fire(self):
        quiet = self.kiosk.scene_from_state(
            {
                "gpu_mode": "llm",
                "kind": "chat",
                "busy": True,
                "stage": "decode",
                "tokens": 0,
            },
            True,
        )
        quiet["st"] = 1.0
        quiet["token_rate"] = 0.0
        quiet["tokens"] = 0
        quiet["stage"] = "decode"
        loud = dict(quiet)
        loud["tokens"] = 48
        loud["token_rate"] = 24.0
        a = self.kiosk.neuron_overlay_state(quiet)
        b = self.kiosk.neuron_overlay_state(loud)
        assert a is not None and b is not None
        self.assertGreater(sum(b["fires"]), sum(a["fires"]))

    def test_image_restore_is_reloading(self):
        scene = self.kiosk.scene_from_state(
            {
                "gpu_mode": "comfy",
                "kind": "image",
                "busy": True,
                "switching": True,
                "stage": "switch",
            },
            True,
        )
        self.assertEqual(scene["phase"], "reloading")
        self.assertEqual(scene["palette"], "switch")


class SaverComposeTests(unittest.TestCase):
    def test_decode_snapshot_wins_for_chat(self):
        weather = saver._compose_weather(
            switching=False,
            restarting=False,
            queue={"busy": True, "kind": "chat", "waiters": 1, "elapsed_s": 4},
            decode={"tokens": 20, "stage": "decode"},
            job=None,
            flights=[],
        )
        self.assertEqual(weather["stage"], "decode")
        self.assertEqual(weather["tokens"], 20)
        self.assertEqual(weather["waiters"], 1)
        self.assertEqual(weather["elapsed_s"], 4)

    def test_flight_chars_when_decode_idle(self):
        flight = SimpleNamespace(
            done=False, assembled="hello world", reasoning="", kind="chat", steps=[]
        )
        weather = saver._compose_weather(
            switching=False,
            restarting=False,
            queue={"busy": True, "kind": "chat"},
            decode={"tokens": 0, "stage": "idle"},
            job=None,
            flights=[flight],
        )
        self.assertEqual(weather["stage"], "decode")
        self.assertEqual(weather["tokens"], len("hello world"))
        self.assertNotIn("hello", repr(weather))

    def test_tool_step_without_result(self):
        flight = SimpleNamespace(
            done=False,
            assembled="x",
            reasoning="",
            kind="code",
            steps=[{"type": "tool", "name": "Read"}],
        )
        weather = saver._compose_weather(
            switching=False,
            restarting=False,
            queue={"busy": True, "kind": "code"},
            decode={"tokens": 0, "stage": "idle"},
            job=None,
            flights=[flight],
        )
        self.assertEqual(weather["stage"], "tool")
        self.assertEqual(weather["tokens"], 1)

    def test_image_job_progress(self):
        job = SimpleNamespace(status="running", phase="generating", count=3, current_index=1)
        weather = saver._compose_weather(
            switching=False,
            restarting=False,
            queue={"busy": True, "kind": "image"},
            decode={"tokens": 0, "stage": "idle"},
            job=job,
            flights=[],
        )
        self.assertEqual(weather["stage"], "image")
        self.assertEqual(weather["image_n"], 2)
        self.assertEqual(weather["image_of"], 3)


class LiveDecodeTests(unittest.TestCase):
    def setUp(self):
        live_decode.reset_for_tests()

    def tearDown(self):
        live_decode.reset_for_tests()

    def test_prefill_then_decode_then_clear(self):
        live_decode.note_prefill("a")
        self.assertEqual(live_decode.snapshot()["stage"], "prefill")
        live_decode.note_decode("a", 7)
        self.assertEqual(live_decode.snapshot(), {"tokens": 7, "stage": "decode"})
        live_decode.clear("b")
        self.assertEqual(live_decode.snapshot()["tokens"], 7)
        live_decode.clear("a")
        self.assertEqual(live_decode.snapshot()["stage"], "idle")
        self.assertEqual(live_decode.snapshot()["tokens"], 0)

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ui import metrics


class UiMetricsTests(unittest.TestCase):
    def setUp(self):
        metrics.reset_for_tests()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "ui_metrics.jsonl"
        self._path_patch = mock.patch.object(metrics, "HISTORY_PATH", self.path)
        self._path_patch.start()
        self.addCleanup(self._path_patch.stop)

    def tearDown(self):
        metrics.reset_for_tests()

    def test_resolve_window_prefers_days(self):
        self.assertEqual(metrics.resolve_window_seconds(days=2), 2 * 86400)
        self.assertEqual(metrics.resolve_window_seconds(hours=6), 6 * 3600)
        self.assertEqual(metrics.resolve_window_seconds(), 24 * 3600)
        self.assertEqual(metrics.resolve_window_seconds(days=100), 30 * 86400)
        self.assertEqual(metrics.resolve_window_seconds(hours=0.01), 3600 / 60)

    def test_downsample_averages_buckets(self):
        points = [{"t": float(i), "cpu": float(i), "gpu": 10.0} for i in range(10)]
        out = metrics.downsample(points, 2)
        self.assertEqual(len(out), 2)
        self.assertIn("cpu", out[0])
        self.assertEqual(out[0]["gpu"], 10.0)

    def test_metrics_history_filters_window(self):
        now = time.time()
        for i in range(5):
            metrics.record_sample(
                {
                    "t": now - (4 - i) * 3600,
                    "cpu": 10 + i,
                    "load1": 1.0,
                    "ram": 40.0,
                    "gpu": 50.0,
                    "vram": 60.0,
                    "temp": 70.0,
                }
            )
        payload = metrics.metrics_history(hours=2.5)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["raw_count"], 2)
        self.assertLessEqual(payload["raw_count"], 3)
        for row in payload["series"]:
            self.assertGreaterEqual(row["t"], now - 2.5 * 3600 - 1)

    def test_take_sample_keys(self):
        fake_psutil = mock.MagicMock()
        fake_psutil.cpu_percent.return_value = 12.5
        fake_psutil.virtual_memory.return_value = mock.Mock(percent=33.0)
        with mock.patch.dict("sys.modules", {"psutil": fake_psutil}):
            with mock.patch(
                "ui.manager.nvidia_stats",
                return_value={
                    "utilization_pct": 40,
                    "memory_used_mib": 4000,
                    "memory_total_mib": 12000,
                    "temperature_c": 55,
                },
            ):
                row = metrics.take_sample(now=12345.0)
        self.assertEqual(row["t"], 12345.0)
        self.assertEqual(row["cpu"], 12.5)
        self.assertEqual(row["ram"], 33.0)
        self.assertEqual(row["gpu"], 40.0)
        self.assertAlmostEqual(row["vram"], 100.0 * 4000 / 12000, places=2)
        self.assertEqual(row["temp"], 55.0)


if __name__ == "__main__":
    unittest.main()

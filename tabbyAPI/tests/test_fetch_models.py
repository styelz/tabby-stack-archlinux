import sys
import tempfile
import unittest
from pathlib import Path

ARCH = Path(__file__).resolve().parents[1] / "deploy" / "arch"
sys.path.insert(0, str(ARCH))

from fetch_models import (  # noqa: E402
    copy_from_cache,
    dest_path,
    find_cache,
    is_ready,
    load_catalog,
    select_ids,
    shards_complete,
    verify_tree,
)


CATALOG = Path(__file__).resolve().parents[1] / "deploy" / "arch" / "models.json"


class FetchModelsTests(unittest.TestCase):
    def test_catalog_sets_are_known_items(self):
        catalog = load_catalog(CATALOG)
        items = catalog["items"]
        for name, members in catalog["sets"].items():
            for item_id in members:
                self.assertIn(item_id, items, msg=f"{name} references missing {item_id}")
        self.assertIn("qwen", catalog["sets"]["core"])
        self.assertIn("qwen36", catalog["sets"]["all"])
        self.assertNotIn("qwen36", catalog["sets"]["core"])

    def test_select_ids_rejects_unknown_set(self):
        with self.assertRaises(SystemExit):
            select_ids({"sets": {"core": ["qwen"]}}, "nope")

    def test_is_ready_file_and_snapshot(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            missing = root / "missing.safetensors"
            self.assertFalse(is_ready(missing, {"kind": "file"}))
            present = root / "flux.safetensors"
            present.write_bytes(b"ok")
            self.assertTrue(is_ready(present, {"kind": "file"}))

            snap = root / "model"
            snap.mkdir()
            item = {"kind": "snapshot", "ready": ["model.safetensors"]}
            self.assertFalse(is_ready(snap, item))
            (snap / "model.safetensors").write_bytes(b"weights")
            self.assertTrue(is_ready(snap, item))

    def test_half_copied_sharded_model_is_not_ready(self):
        item = {"kind": "snapshot", "ready": ["model.safetensors", "quantization_config.json"]}
        with tempfile.TemporaryDirectory() as raw:
            snap = Path(raw)
            (snap / "quantization_config.json").write_text("{}", encoding="utf-8")
            (snap / "model-00001-of-00002.safetensors").write_bytes(b"shard one")
            self.assertIs(shards_complete(snap), False)
            self.assertFalse(is_ready(snap, item))

            (snap / "model-00002-of-00002.safetensors").write_bytes(b"shard two")
            self.assertIs(shards_complete(snap), True)
            self.assertTrue(is_ready(snap, item))

    def test_interrupted_download_marker_blocks_ready(self):
        item = {"kind": "snapshot", "ready": ["model.safetensors"]}
        with tempfile.TemporaryDirectory() as raw:
            snap = Path(raw)
            (snap / "model.safetensors").write_bytes(b"weights")
            self.assertTrue(is_ready(snap, item))
            partial = snap / ".cache" / "huggingface" / "download"
            partial.mkdir(parents=True)
            (partial / "model.safetensors.incomplete").write_bytes(b"partial")
            self.assertFalse(is_ready(snap, item))

    def test_file_copy_is_atomic_and_size_checked(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            src = root / "src.safetensors"
            src.write_bytes(b"x" * 4096)
            dest = root / "out" / "dest.safetensors"
            copy_from_cache(src, dest, "file")
            self.assertEqual(dest.read_bytes(), src.read_bytes())
            self.assertEqual(list(dest.parent.glob(".*.part")), [])

    def test_folder_copy_is_verified_against_the_source(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            src = root / "src"
            src.mkdir()
            (src / "model.safetensors").write_bytes(b"y" * 2048)
            dest = root / "dest"
            copy_from_cache(src, dest, "snapshot")
            self.assertEqual((dest / "model.safetensors").stat().st_size, 2048)
            verify_tree(src, dest)

            (dest / "model.safetensors").write_bytes(b"y")
            with self.assertRaises(SystemExit):
                verify_tree(src, dest)

            (dest / "model.safetensors").unlink()
            with self.assertRaises(SystemExit):
                verify_tree(src, dest)

    def test_dest_and_cache_lookup(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tabby = root / "tabby"
            comfy = root / "comfy"
            cache = root / "cache"
            dest = dest_path({"dest": "tabby/models/Qwen3.5-9B-exl3-4.00bpw"}, tabby, comfy)
            self.assertEqual(dest, tabby / "models" / "Qwen3.5-9B-exl3-4.00bpw")

            item = {
                "kind": "file",
                "dest": "comfy/models/checkpoints/flux1-schnell-fp8.safetensors",
                "cache": ["ComfyUI/models/checkpoints/flux1-schnell-fp8.safetensors"],
            }
            self.assertIsNone(find_cache(item, cache))
            cached = cache / "ComfyUI/models/checkpoints/flux1-schnell-fp8.safetensors"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"flux")
            self.assertEqual(find_cache(item, cache), cached.resolve())

    def test_find_cache_searches_layout_variants(self):
        snap_item = {
            "kind": "snapshot",
            "dest": "tabby/models/Qwen3.5-9B-exl3-4.00bpw",
            "cache": ["tabbyAPI/models/Qwen3.5-9B-exl3-4.00bpw"],
            "ready": ["model.safetensors"],
        }
        file_item = {
            "kind": "file",
            "dest": "comfy/models/checkpoints/flux1-schnell-fp8.safetensors",
            "cache": ["ComfyUI/models/checkpoints/flux1-schnell-fp8.safetensors"],
        }

        def ready_snap(path: Path) -> Path:
            path.mkdir(parents=True)
            (path / "model.safetensors").write_bytes(b"weights")
            return path

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            models_dir = root / "just-models"
            snap = ready_snap(models_dir / "Qwen3.5-9B-exl3-4.00bpw")
            self.assertEqual(find_cache(snap_item, models_dir), snap.resolve())

            tabby_root = root / "tabbyAPI"
            snap = ready_snap(tabby_root / "models" / "Qwen3.5-9B-exl3-4.00bpw")
            self.assertEqual(find_cache(snap_item, tabby_root), snap.resolve())

            usb = root / "usb"
            snap = ready_snap(
                usb / "tabby-stack" / "tabbyAPI" / "models" / "Qwen3.5-9B-exl3-4.00bpw"
            )
            self.assertEqual(find_cache(snap_item, usb), snap.resolve())

            self.assertEqual(find_cache(snap_item, snap), snap.resolve())

            loose = root / "loose"
            loose.mkdir()
            flux = loose / "flux1-schnell-fp8.safetensors"
            flux.write_bytes(b"flux")
            self.assertEqual(find_cache(file_item, loose), flux.resolve())

            nested = root / "nested" / "copy"
            flux = nested / "extra" / "flux1-schnell-fp8.safetensors"
            flux.parent.mkdir(parents=True)
            flux.write_bytes(b"flux")
            self.assertEqual(find_cache(file_item, nested), flux.resolve())

    def test_find_cache_hub_snapshot(self):
        item = {
            "kind": "snapshot",
            "repo": "turboderp/Qwen3.5-9B-exl3",
            "revision": "4.00bpw",
            "dest": "tabby/models/Qwen3.5-9B-exl3-4.00bpw",
            "cache": ["tabbyAPI/models/Qwen3.5-9B-exl3-4.00bpw"],
            "ready": ["model.safetensors"],
        }
        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw)
            snap = (
                cache
                / "hub"
                / "models--turboderp--Qwen3.5-9B-exl3"
                / "snapshots"
                / "4.00bpw"
            )
            snap.mkdir(parents=True)
            (snap / "model.safetensors").write_bytes(b"weights")
            self.assertEqual(find_cache(item, cache), snap.resolve())


if __name__ == "__main__":
    unittest.main()

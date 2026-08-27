"""Jailed UI Code-mode project folders."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ui import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        workspace.set_workspaces_dir(self.root)

    def tearDown(self):
        workspace.set_workspaces_dir(None)
        self._tmp.cleanup()

    def test_rejects_dotdot_and_absolute_paths(self):
        with self.assertRaises(ValueError):
            workspace.write_text("u", "c", "../x.txt", "no")
        with self.assertRaises(ValueError):
            workspace.write_text("u", "c", "/tmp/x.txt", "no")

    def test_write_replace_and_rename_keeps_history(self):
        workspace.write_text("u", "c", "a.txt", "one")
        workspace.write_text("u", "c", "a.txt", "two")
        workspace.str_replace("u", "c", "a.txt", "two", "three")
        self.assertEqual(workspace.read_text("u", "c", "a.txt"), "three")
        workspace.rename_file("u", "c", "a.txt", "b.txt")
        self.assertEqual(workspace.read_text("u", "c", "b.txt"), "three")
        versions = workspace.list_history("u", "c", "b.txt")
        self.assertTrue(versions)

    def test_delete_cleans_empty_parents(self):
        workspace.write_text("u", "c", "css/a.css", "x")
        workspace.delete_file("u", "c", "css/a.css")
        root = workspace.workspace_root("u", "c")
        self.assertFalse((root / "css").exists())

    def test_rename_and_delete_prefix(self):
        workspace.write_text("u", "c", "css/a.css", "a")
        workspace.write_text("u", "c", "css/b.css", "b")
        moved = workspace.rename_prefix("u", "c", "css", "styles")
        self.assertEqual({dst for _src, dst in moved}, {"styles/a.css", "styles/b.css"})
        deleted = workspace.delete_prefix("u", "c", "styles")
        self.assertEqual(set(deleted), {"styles/a.css", "styles/b.css"})
        self.assertEqual(workspace.list_files("u", "c"), [])

    def test_caps_limit_file_count(self):
        with mock.patch.object(workspace, "MAX_FILES", 2):
            workspace.write_text("u", "c", "a.txt", "1")
            workspace.write_text("u", "c", "b.txt", "2")
            with self.assertRaises(ValueError):
                workspace.write_text("u", "c", "c.txt", "3")

    def test_drafts_sidecar_stays_outside_project(self):
        workspace.write_text("u", "c", "a.txt", "one")
        saved = workspace.save_drafts("u", "c", [{"path": "a.txt", "text": "two", "caret": [1, 2]}])
        self.assertEqual(saved[0]["path"], "a.txt")
        self.assertEqual(saved[0]["text"], "two")
        self.assertEqual(workspace.load_drafts("u", "c")[0]["text"], "two")
        root = workspace.workspace_root("u", "c")
        self.assertFalse((root / "a.txt.drafts.json").exists())
        self.assertTrue(workspace.drafts_path("u", "c").is_file())
        self.assertNotEqual(workspace.drafts_path("u", "c").parent, root)
        workspace.drop_draft("u", "c", "a.txt")
        self.assertEqual(workspace.load_drafts("u", "c"), [])
        workspace.save_drafts("u", "c", [{"path": "a.txt", "text": "x"}])
        workspace.delete_workspace("u", "c")
        self.assertFalse(workspace.drafts_path("u", "c").exists())

    def test_optimize_image_trims_white_border(self):
        from PIL import Image

        from images.trim import trim_image

        canvas = Image.new("RGB", (80, 80), "white")
        for x in range(20, 60):
            for y in range(20, 60):
                canvas.putpixel((x, y), (10, 20, 180))
        cropped, box = trim_image(canvas, color=(255, 255, 255))
        self.assertEqual(box, (20, 20, 60, 60))
        self.assertEqual(cropped.size, (40, 40))

        import io

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        workspace.copy_bytes("u", "c", "star.png", buf.getvalue())
        result = workspace.optimize_image("u", "c", "star.png", trim_border=True)
        self.assertTrue(result["trimmed"])
        self.assertEqual(result["dimensions"], "40x40")
        self.assertEqual(result["original_dimensions"], "80x80")

    def _write_png(self, rel, width, height, fill="white", ink=None, ink_box=None):
        from PIL import Image

        import io

        canvas = Image.new("RGB", (width, height), fill)
        if ink and ink_box:
            left, top, right, bottom = ink_box
            for x in range(left, right):
                for y in range(top, bottom):
                    canvas.putpixel((x, y), ink)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        workspace.copy_bytes("u", "c", rel, buf.getvalue())

    def test_crop_image_png_box(self):
        from PIL import Image

        self._write_png(
            "pic.png",
            80,
            60,
            fill="white",
            ink=(200, 10, 10),
            ink_box=(10, 5, 50, 35),
        )
        result = workspace.crop_image("u", "c", "pic.png", 10, 5, 40, 30)
        self.assertEqual(result["path"], "pic.png")
        self.assertEqual(result["original_dimensions"], "80x60")
        self.assertEqual(result["dimensions"], "40x30")
        path = workspace.resolve_file("u", "c", "pic.png")
        with Image.open(path) as cropped:
            self.assertEqual(cropped.size, (40, 30))
            self.assertEqual(cropped.getpixel((0, 0)), (200, 10, 10))

    def test_crop_image_empty_box_after_clamp(self):
        self._write_png("pic.png", 80, 60)
        with self.assertRaises(ValueError):
            workspace.crop_image("u", "c", "pic.png", 90, 0, 10, 10)
        with self.assertRaises(ValueError):
            workspace.crop_image("u", "c", "pic.png", 0, 0, 0, 10)
        with self.assertRaises(ValueError):
            workspace.crop_image("u", "c", "pic.png", 20, 10, -8, 10)

    def test_crop_image_rejects_animated_gif(self):
        from PIL import Image

        import io

        frames = [Image.new("RGB", (8, 8), color) for color in ("red", "blue")]
        buf = io.BytesIO()
        frames[0].save(
            buf,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
        )
        workspace.copy_bytes("u", "c", "spin.gif", buf.getvalue())
        with self.assertRaises(ValueError):
            workspace.crop_image("u", "c", "spin.gif", 0, 0, 4, 4)


if __name__ == "__main__":
    unittest.main()

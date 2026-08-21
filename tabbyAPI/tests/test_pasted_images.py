import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import pasted_images
from endpoints.OAI.types.chat_completion import (
    ChatCompletionMessage,
    ChatCompletionMessagePart,
    ChatCompletionRequest,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"p" * 64
JPEG_BYTES = b"\xff\xd8\xff" + b"j" * 64


def _data_uri(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _paste(raw: bytes, mime: str = "image/png") -> ChatCompletionRequest:
    part = ChatCompletionMessagePart(
        type="image_url",
        image_url={"url": _data_uri(raw, mime)},
    )
    return ChatCompletionRequest(messages=[ChatCompletionMessage(role="user", content=[part])])


class PastedImageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        folder = Path(self._tmp.name)
        patches = (
            mock.patch.object(pasted_images, "SAVE_DIR", folder),
            mock.patch.object(pasted_images, "LATEST", folder / "latest.png"),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.folder = folder
        self.addCleanup(self._tmp.cleanup)

    def test_png_paste_writes_latest_png(self):
        saved = pasted_images.materialize_pasted_images(_paste(PNG_BYTES))
        self.assertEqual(len(saved), 1)
        self.assertEqual((self.folder / "latest.png").read_bytes(), PNG_BYTES)

    def test_jpeg_paste_never_lands_in_latest_png(self):
        saved = pasted_images.materialize_pasted_images(_paste(JPEG_BYTES, "image/jpeg"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].suffix, ".jpg")
        self.assertEqual((self.folder / "latest.jpg").read_bytes(), JPEG_BYTES)
        self.assertFalse((self.folder / "latest.png").exists())

    def test_resent_history_does_not_pile_up_copies(self):
        data = _paste(PNG_BYTES)
        first = pasted_images.materialize_pasted_images(data)
        second = pasted_images.materialize_pasted_images(data)
        self.assertEqual(first, second)
        stored = [p for p in self.folder.glob("*.png") if p.name != "latest.png"]
        self.assertEqual(len(stored), 1)

    def test_prune_keeps_newest_and_spares_aliases(self):
        for index in range(5):
            path = self.folder / f"20260101T00000{index}-1-{index:016x}.png"
            path.write_bytes(PNG_BYTES + bytes([index]))
        (self.folder / "latest.png").write_bytes(PNG_BYTES)
        removed = pasted_images.prune_saved_images(keep=2)
        self.assertEqual(len(removed), 3)
        self.assertTrue((self.folder / "latest.png").exists())
        stored = [p for p in self.folder.glob("*.png") if p.name != "latest.png"]
        self.assertEqual(len(stored), 2)

    def test_resolve_save_dest_keeps_the_extension(self):
        dest = pasted_images.resolve_save_dest(
            "save the screenshot to notes/shot.png", workspace=Path.home()
        )
        self.assertEqual(dest.name, "shot.png")

    def test_resolve_save_dest_uses_the_last_filename(self):
        dest = pasted_images.resolve_save_dest(
            "copy latest.png to final.png", workspace=Path.home()
        )
        self.assertEqual(dest.name, "final.png")

    def test_pasted_download_text_is_a_remote_curl(self):
        (self.folder / "latest.png").write_bytes(PNG_BYTES)
        text = pasted_images.pasted_download_text(
            "save the screenshot to notes/shot.png",
            "http://gpu.example:5000/v1",
        )
        self.assertIn("http://gpu.example:5000/v1/images/pasted/latest.png", text)
        self.assertIn("shot.png", text)
        self.assertNotIn("curl ", text)
        self.assertNotIn("/mnt/d/", text)

    def test_pasted_image_path_stays_in_folder(self):
        (self.folder / "latest.png").write_bytes(PNG_BYTES)
        self.assertEqual(
            pasted_images.pasted_image_path("latest.png"),
            (self.folder / "latest.png").resolve(),
        )
        self.assertIsNone(pasted_images.pasted_image_path("../latest.png"))


if __name__ == "__main__":
    unittest.main()

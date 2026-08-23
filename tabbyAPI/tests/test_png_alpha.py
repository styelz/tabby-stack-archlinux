import io
import unittest

from PIL import Image

from common.png_alpha import apply_requested_alpha


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class PngAlphaTests(unittest.TestCase):
    def test_alpha_punch_is_disabled(self):
        im = Image.new("RGB", (64, 64), (255, 0, 255))
        for y in range(20, 44):
            for x in range(20, 44):
                im.putpixel((x, y), (200, 40, 40))
        raw = _png(im)
        self.assertIs(apply_requested_alpha(raw, wanted=False), raw)
        self.assertIs(apply_requested_alpha(raw, wanted=True), raw)

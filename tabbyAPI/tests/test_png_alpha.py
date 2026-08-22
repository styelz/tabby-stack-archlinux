import io
import unittest

from PIL import Image

from common.png_alpha import apply_requested_alpha


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _open(raw: bytes) -> Image.Image:
    return Image.open(io.BytesIO(raw))


def _transparent_count(im: Image.Image) -> int:
    rgba = im.convert("RGBA")
    return sum(1 for pixel in rgba.getdata() if pixel[3] < 128)


class PngAlphaTests(unittest.TestCase):
    def test_wanted_false_leaves_bytes_alone(self):
        raw = _png(Image.new("RGB", (32, 32), (40, 80, 120)))
        self.assertIs(apply_requested_alpha(raw, wanted=False), raw)
        self.assertEqual(apply_requested_alpha(raw, wanted=False), raw)

    def test_magenta_chroma_becomes_alpha(self):
        im = Image.new("RGB", (64, 64), (255, 0, 255))
        for y in range(20, 44):
            for x in range(20, 44):
                im.putpixel((x, y), (200, 40, 40))
        out = apply_requested_alpha(_png(im), wanted=True)
        result = _open(out)
        self.assertEqual(result.mode, "RGBA")
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((63, 63))[3], 0)
        subject = result.getpixel((32, 32))
        self.assertGreater(subject[3], 200)
        self.assertGreater(subject[0], 150)

    def test_checkerboard_becomes_alpha(self):
        light = (255, 255, 255)
        dark = (192, 192, 192)
        im = Image.new("RGB", (64, 64))
        for y in range(64):
            for x in range(64):
                im.putpixel(
                    (x, y),
                    light if ((x // 8) + (y // 8)) % 2 == 0 else dark,
                )
        for y in range(24, 40):
            for x in range(24, 40):
                im.putpixel((x, y), (20, 90, 200))
        out = apply_requested_alpha(_png(im), wanted=True)
        result = _open(out)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((8, 0))[3], 0)
        subject = result.getpixel((32, 32))
        self.assertGreater(subject[3], 200)
        self.assertEqual(subject[:3], (20, 90, 200))

    def test_already_transparent_is_unchanged(self):
        im = Image.new("RGBA", (64, 64), (10, 20, 30, 255))
        for y in range(16, 48):
            for x in range(16, 48):
                im.putpixel((x, y), (10, 20, 30, 0))
        raw = _png(im)
        out = apply_requested_alpha(raw, wanted=True)
        self.assertEqual(out, raw)
        self.assertGreater(_transparent_count(_open(out)), 500)

    def test_white_studio_backdrop_becomes_alpha(self):
        im = Image.new("RGB", (64, 64), (250, 250, 250))
        for y in range(18, 46):
            for x in range(18, 46):
                im.putpixel((x, y), (20, 90, 200))
        out = apply_requested_alpha(_png(im), wanted=True)
        result = _open(out)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((63, 63))[3], 0)
        subject = result.getpixel((32, 32))
        self.assertGreater(subject[3], 200)
        self.assertEqual(subject[:3], (20, 90, 200))

    def test_dark_space_around_a_planet_becomes_alpha(self):
        im = Image.new("RGB", (64, 64), (4, 4, 12))
        for y in range(16, 48):
            for x in range(16, 48):
                if (x - 32) ** 2 + (y - 32) ** 2 <= 14 ** 2:
                    im.putpixel((x, y), (200, 70, 40))
        out = apply_requested_alpha(_png(im), wanted=True)
        result = _open(out)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((63, 0))[3], 0)
        subject = result.getpixel((32, 32))
        self.assertGreater(subject[3], 200)
        self.assertGreater(subject[0], 150)

    def test_subject_color_matching_old_chroma_is_kept(self):
        """A mark the same color as the old #FF00FF key must stay opaque."""
        im = Image.new("RGB", (64, 64), (255, 255, 255))
        for y in range(20, 44):
            for x in range(20, 44):
                im.putpixel((x, y), (255, 0, 255))
        out = apply_requested_alpha(_png(im), wanted=True)
        result = _open(out)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        mark = result.getpixel((32, 32))
        self.assertGreater(mark[3], 200)
        self.assertEqual(mark[:3], (255, 0, 255))

    def test_white_studio_with_checkerboard_floor_becomes_alpha(self):
        """Flux often paints a fake transparency grid only on the bottom."""
        light = (255, 255, 255)
        dark = (190, 190, 190)
        im = Image.new("RGB", (64, 64), light)
        for y in range(48, 64):
            for x in range(64):
                im.putpixel(
                    (x, y),
                    light if ((x // 8) + (y // 8)) % 2 == 0 else dark,
                )
        for y in range(16, 48):
            for x in range(16, 48):
                if (x - 32) ** 2 + (y - 32) ** 2 <= 14 ** 2:
                    im.putpixel((x, y), (210, 90, 40))
        out = apply_requested_alpha(_png(im), wanted=True)
        result = _open(out)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((8, 63))[3], 0)
        self.assertEqual(result.getpixel((40, 63))[3], 0)
        subject = result.getpixel((32, 32))
        self.assertGreater(subject[3], 200)
        self.assertGreater(subject[0], 150)

    def test_small_corner_studio_blob_is_removed(self):
        im = Image.new("RGB", (64, 64), (250, 250, 250))
        for y in range(18, 46):
            for x in range(18, 46):
                im.putpixel((x, y), (20, 90, 200))
        for y in range(52, 64):
            for x in range(0, 12):
                im.putpixel((x, y), (160, 165, 170))
        out = apply_requested_alpha(_png(im), wanted=True)
        result = _open(out)
        self.assertEqual(result.getpixel((2, 60))[3], 0)
        subject = result.getpixel((32, 32))
        self.assertGreater(subject[3], 200)
        self.assertEqual(subject[:3], (20, 90, 200))


if __name__ == "__main__":
    unittest.main()

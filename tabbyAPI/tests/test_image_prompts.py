import json
import unittest

from common.gpu_mode import wants_qwen_image
from common.image_prompts import (
    SCENE_TAIL,
    mixed_image_plan_text,
    plan_mixed_images,
    rewrite_comfy_prompt,
    site_folder,
    user_asked_for_svg,
)


class ImagePromptRewriteTests(unittest.TestCase):
    def test_plain_scene_is_unchanged(self):
        text = "a fox asleep under maple trees"
        self.assertEqual(rewrite_comfy_prompt(text), text)
        self.assertFalse(wants_qwen_image(text))

    def test_text_assets_stay_on_qwen(self):
        poster = "a poster with the heading SALE"
        self.assertEqual(rewrite_comfy_prompt(poster), poster)
        self.assertTrue(wants_qwen_image(poster))
        self.assertTrue(wants_qwen_image("qwen-image: login form with Submit"))
        self.assertTrue(wants_qwen_image("UI mockup of a settings screen"))
        self.assertTrue(wants_qwen_image("a red button labeled Start"))

    def test_website_hero_becomes_flux_scene(self):
        rewritten = rewrite_comfy_prompt(
            "modern website hero banner for Lumina, purple gradient UI"
        )
        self.assertNotIn("qwen-image:", rewritten.lower())
        self.assertIn("no website", rewritten)
        self.assertIn(SCENE_TAIL.split(",")[0], rewritten)
        self.assertFalse(wants_qwen_image(rewritten))
        self.assertFalse(
            wants_qwen_image("qwen-image: website header banner, completed homepage")
        )

    def test_logo_keeps_qwen_and_drops_website(self):
        rewritten = rewrite_comfy_prompt(
            "elegant logo that says Lumina for the website header"
        )
        self.assertTrue(rewritten.lower().startswith("qwen-image:"))
        self.assertIn("Lumina", rewritten)
        self.assertNotIn("website", rewritten.lower())
        self.assertTrue(wants_qwen_image(rewritten))

    def test_rewrite_is_idempotent(self):
        first = rewrite_comfy_prompt("cosmic nebula website header banner")
        self.assertEqual(rewrite_comfy_prompt(first), first)

    def test_svg_noise_does_not_keep_a_logo_off_qwen(self):
        rewritten = rewrite_comfy_prompt("svg css-art logo that says Cafe")
        self.assertTrue(rewritten.lower().startswith("qwen-image:"))
        self.assertNotIn("svg", rewritten.lower())
        self.assertNotIn("css-art", rewritten.lower())

    def test_planet_website_image_becomes_flux_photo(self):
        rewritten = rewrite_comfy_prompt(
            "css generated image of saturn for the website card"
        )
        self.assertNotIn("qwen-image:", rewritten.lower())
        self.assertIn("Saturn", rewritten)
        self.assertFalse(wants_qwen_image(rewritten))

    def test_planet_tours_prompt_plans_logo_and_eight_pngs(self):
        line = (
            "create a one page website , the site is a solar systme tours "
            "booking page where people can visit other plantes. I want a nice "
            'logo image for the company "Planet By Planet Tours". I want a bit '
            "of information on each planet along with an image of each planet "
            "and what it has to offer. The entire site should be placed under "
            "the folder pbptours. all images generated should be placed in the "
            "pbptours/images folder. The site should be reactive and look "
            "slick and spacey."
        )
        items = plan_mixed_images(line)
        paths = [row["output_path"] for row in items]
        self.assertEqual(site_folder(line), "pbptours")
        self.assertEqual(paths[0], "pbptours/images/logo.png")
        self.assertTrue(items[0]["prompt"].lower().startswith("qwen-image:"))
        self.assertIn("Planet By Planet Tours", items[0]["prompt"])
        self.assertEqual(
            paths[1:],
            [
                "pbptours/images/mercury.png",
                "pbptours/images/venus.png",
                "pbptours/images/earth.png",
                "pbptours/images/mars.png",
                "pbptours/images/jupiter.png",
                "pbptours/images/saturn.png",
                "pbptours/images/uranus.png",
                "pbptours/images/neptune.png",
            ],
        )
        for row in items[1:]:
            self.assertNotIn("qwen-image:", row["prompt"].lower())
            self.assertNotIn("svg", row["prompt"].lower())
        brief = mixed_image_plan_text(line)
        payload = json.loads(brief.splitlines()[-1])
        self.assertEqual(len(payload["images"]), 9)
        self.assertIn("pbptours/images/logo.png", brief)
        self.assertNotIn('says "Planet By Planet Tours"', items[0]["prompt"])
        self.assertIn("Do not use generate_image", brief)
        self.assertNotIn("Call generate_image", brief)
        self.assertNotIn("--data-binary", brief)
        self.assertNotIn("/v1/mcp", brief)
        self.assertFalse(user_asked_for_svg(line))
        self.assertFalse(
            user_asked_for_svg(
                "svg images were generated instead of png images, can you fix that"
            )
        )
        self.assertTrue(user_asked_for_svg("please use SVG icons for the nav"))


if __name__ == "__main__":
    unittest.main()

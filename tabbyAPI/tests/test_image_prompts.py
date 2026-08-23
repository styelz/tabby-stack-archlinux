import json
import unittest

from common.gpu_mode import wants_qwen_image
from common.image_prompts import (
    CHROMA_HEX,
    CUTOUT_TAIL,
    GPU_PNG_NOTE,
    SCENE_TAIL,
    images_folder,
    mixed_image_plan_text,
    neutralize_local_image_script,
    plan_image_redo,
    plan_mixed_images,
    rewrite_comfy_prompt,
    site_folder,
    company_name,
    user_asked_for_svg,
    wants_transparent,
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
        self.assertIn("isolated logo mark", rewritten.lower())
        self.assertIn("no page layout", rewritten.lower())
        self.assertTrue(wants_qwen_image(rewritten))
        again = rewrite_comfy_prompt(rewritten)
        self.assertEqual(again, rewritten)

    def test_website_spec_logo_collapses_to_isolated_mark(self):
        line = (
            'Create a complete, production-ready website for a solar system '
            'tour company called "Cosmos Tours." The website should be a '
            "single-page application with a hero section, contact form, "
            "booking system, and pricing tiers. All images must be generated "
            "as transparent PNG files using Python with PIL/Pillow. The logo "
            "should be large. Deliverables: Complete HTML/CSS/JS and a Python "
            "script to generate the logo, planets, and icons."
        )
        self.assertEqual(company_name(line), "Cosmos Tours")
        rewritten = rewrite_comfy_prompt(line)
        self.assertTrue(rewritten.lower().startswith("qwen-image:"))
        self.assertIn("Cosmos Tours", rewritten)
        self.assertNotIn("Cosmos Tours.", rewritten)
        self.assertIn("isolated logo mark", rewritten.lower())
        self.assertNotIn("single-page", rewritten.lower())
        self.assertNotIn("pillow", rewritten.lower())
        self.assertNotIn("contact form", rewritten.lower())
        self.assertNotIn("booking", rewritten.lower())
        self.assertLess(len(rewritten), 360)
        self.assertNotIn("transparent", rewritten.lower())
        self.assertNotIn(CHROMA_HEX, rewritten)
        self.assertNotIn(CUTOUT_TAIL.split(",")[0], rewritten)
        items = plan_mixed_images(line)
        self.assertEqual(items[0]["output_path"], "images/logo.png")
        self.assertEqual(items[0]["prompt"], rewritten)

    def test_api_image_url_is_not_a_project_folder(self):
        line = (
            'create a website for a company called "Cosmos Tours" with a logo '
            "image and transparent PNG images of Mars, Jupiter and Saturn. "
            "The pasted image lives at "
            "https://git.pbptech.com/openai/v1/images/pasted/latest.png"
        )
        self.assertEqual(images_folder(line), "images")
        self.assertEqual(site_folder(line), "")
        items = plan_mixed_images(line)
        paths = [row["output_path"] for row in items]
        self.assertTrue(all(path.startswith("images/") for path in paths))
        self.assertFalse(any(path.startswith("v1/") for path in paths))
        self.assertIn("images/logo.png", paths)
        self.assertIn("images/mars.png", paths)
        header = next(
            (row for row in items if row["output_path"].endswith("header.png")),
            None,
        )
        if header:
            self.assertNotIn("qwen-image:", header["prompt"].lower())
            self.assertIn(SCENE_TAIL.split(",")[0], header["prompt"])

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

    def test_unnamed_each_item_does_not_invent_a_category(self):
        """'image of each planet' with no names is logo-only. Do not invent
        Mercury–Neptune (that only works for this one site)."""
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
        self.assertEqual(paths, ["pbptours/images/logo.png"])
        self.assertTrue(items[0]["prompt"].lower().startswith("qwen-image:"))
        self.assertIn("Planet By Planet Tours", items[0]["prompt"])
        brief = mixed_image_plan_text(line)
        payload = json.loads(brief.splitlines()[-1])
        self.assertEqual(len(payload["images"]), 1)
        self.assertIn("pbptours/images/logo.png", brief)
        self.assertNotIn("saturn.png", brief)
        self.assertNotIn('says "Planet By Planet Tours"', items[0]["prompt"])
        self.assertIn("Do not use generate_image", brief)
        self.assertNotIn("Call generate_image", brief)
        self.assertNotIn("--data-binary", brief)
        self.assertNotIn("/v1/mcp", brief)
        self.assertIn("generate_images.py", brief)
        self.assertIn("Pillow/PIL", brief)
        self.assertFalse(user_asked_for_svg(line))
        self.assertFalse(
            user_asked_for_svg(
                "svg images were generated instead of png images, can you fix that"
            )
        )
        self.assertTrue(user_asked_for_svg("please use SVG icons for the nav"))

    def test_site_folder_from_bare_under_phrase(self):
        """'under <name>' with no 'folder' word must still be detected.

        This is the exact phrasing from a real mixed ask; before the fix
        every planned PNG collapsed to workspace-root images/ instead of
        pbptours/images/.
        """
        self.assertEqual(
            site_folder(
                "create a site under pbptours and generate a logo + an "
                "image of each planet"
            ),
            "pbptours",
        )
        self.assertEqual(
            site_folder("create a site under pbptours."), "pbptours"
        )
        self.assertEqual(
            site_folder(
                "create a site under pbptours, generate a logo and header "
                "images"
            ),
            "pbptours",
        )
        items = plan_mixed_images(
            "create a site under pbptours and generate a logo + an image "
            "of each planet"
        )
        paths = [row["output_path"] for row in items]
        self.assertTrue(all(path.startswith("pbptours/images/") for path in paths))

    def test_site_folder_ignores_unrelated_under_phrases(self):
        """Common English 'under X' phrases must not be read as a site name."""
        self.assertEqual(
            site_folder(
                "the project is under active development and will include "
                "a logo image"
            ),
            "",
        )
        self.assertEqual(
            site_folder("the site is under construction and needs a logo"),
            "",
        )

    def test_logo_redo_is_one_dest_and_honors_flux(self):
        line = (
            "use flux generate the logo image, it should be an image of an "
            "atom with electrons swirling around it and be transparent "
            "background and rectangle not square"
        )
        items = plan_image_redo(line, "pbptours")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["output_path"], "pbptours/images/logo.png")
        self.assertEqual(items[0]["size"], "1536x768")
        self.assertIn("atom", items[0]["prompt"].lower())
        self.assertTrue(items[0]["prompt"].lower().startswith("flux:"))
        self.assertNotIn("qwen-image:", items[0]["prompt"].lower())
        self.assertNotIn("transparent", items[0]["prompt"].lower())
        self.assertNotIn(CHROMA_HEX, items[0]["prompt"])
        self.assertNotIn(CUTOUT_TAIL, items[0]["prompt"])
        self.assertFalse(wants_qwen_image(items[0]["prompt"]))
        qwen = plan_image_redo(
            "improve the logo, generate a better png image", "pbptours"
        )
        self.assertEqual(qwen[0]["output_path"], "pbptours/images/logo.png")
        self.assertTrue(qwen[0]["prompt"].lower().startswith("qwen-image:"))

    def test_named_planets_queue_flux_photos_not_all_eight(self):
        line = (
            "create a website for Cosmos Tours with a nice logo image and "
            "transparent PNG images of Mars, Jupiter, Saturn and Neptune. "
            "Put files under llm-testing."
        )
        self.assertEqual(company_name(line), "Cosmos Tours")
        items = plan_mixed_images(line)
        paths = [row["output_path"] for row in items]
        self.assertEqual(
            paths,
            [
                "llm-testing/images/logo.png",
                "llm-testing/images/mars.png",
                "llm-testing/images/jupiter.png",
                "llm-testing/images/saturn.png",
                "llm-testing/images/neptune.png",
            ],
        )
        logo = items[0]["prompt"].lower()
        self.assertTrue(logo.startswith("qwen-image:"))
        self.assertIn("cosmos tours", logo)
        self.assertNotIn("transparent", logo)
        self.assertNotIn(CHROMA_HEX.lower(), logo)
        self.assertNotIn(CUTOUT_TAIL.split(",")[0], logo)
        self.assertIn("isolated logo mark", logo)
        self.assertNotIn("website", logo)
        self.assertNotIn("space-tourism", logo)
        for row in items[1:]:
            self.assertNotIn("qwen-image:", row["prompt"].lower())
            self.assertNotIn("transparent", row["prompt"].lower())
            self.assertNotIn(CHROMA_HEX, row["prompt"])
            self.assertNotIn(CUTOUT_TAIL.split(",")[0], row["prompt"])
            self.assertIn(SCENE_TAIL.split(",")[0], row["prompt"])
            self.assertFalse(wants_qwen_image(row["prompt"]))

    def test_cosmos_tours_production_spec_queues_named_planets(self):
        """The live VS Code prompt says 'The logo should be large' and lists
        Mars/Jupiter/Saturn/Neptune. These regex planner tests are not the
        mixed control plane (see images.plan / test_images_chat)."""
        line = (
            'Create a complete, production-ready website for a solar system '
            'tour company called "Cosmos Tours." The website should be a '
            "single-page application. The logo should be large and "
            "prominently displayed. Package section displaying tours to "
            "different planets (Mars, Jupiter, Saturn, Neptune, etc.). "
            "Each planet package should have a generated transparent PNG "
            "image of that planet."
        )
        items = plan_mixed_images(line)
        paths = [row["output_path"] for row in items]
        self.assertEqual(
            paths,
            [
                "images/logo.png",
                "images/mars.png",
                "images/jupiter.png",
                "images/saturn.png",
                "images/neptune.png",
            ],
        )
        logo = items[0]["prompt"].lower()
        self.assertTrue(logo.startswith("qwen-image:"))
        self.assertNotIn("transparent", logo)
        self.assertNotIn(CHROMA_HEX.lower(), logo)
        self.assertNotIn(CUTOUT_TAIL.split(",")[0], logo)
        for row in items[1:]:
            self.assertNotIn("transparent", row["prompt"].lower())
            self.assertNotIn(CHROMA_HEX, row["prompt"])
            self.assertNotIn(CUTOUT_TAIL, row["prompt"])
            self.assertIn(SCENE_TAIL.split(",")[0], row["prompt"])
            self.assertFalse(wants_qwen_image(row["prompt"]))

    def test_cosmos_spec_does_not_queue_css3_or_pricing_junk(self):
        """Live specs list HTML5/CSS3 and 'image of that planet - Multiple
        pricing tiers (Basic, Premium…)'. Those must not become PNGs."""
        line = (
            'Create a complete, production-ready website for a solar system '
            'tour company called "Cosmos Tours." The website should be a '
            "single-page application. All images must be generated as "
            "transparent PNG files (not SVG). The logo should be large. "
            "Package section displaying tours to different planets (Mars, "
            "Jupiter, Saturn, Neptune, etc.). Each planet package should "
            "have a generated transparent PNG image of that planet - "
            "Multiple pricing tiers (Basic, Premium, Luxury). "
            "Use modern HTML5, CSS3, and JavaScript (or React/Vue). "
            "Python script to generate all required transparent PNG images "
            "(logo, planets, icons)."
        )
        paths = [row["output_path"] for row in plan_mixed_images(line)]
        self.assertEqual(
            paths,
            [
                "images/logo.png",
                "images/mars.png",
                "images/jupiter.png",
                "images/saturn.png",
                "images/neptune.png",
            ],
        )
        self.assertNotIn("images/css3.png", paths)
        self.assertNotIn("images/premium.png", paths)
        self.assertFalse(any("pricing" in path for path in paths))

    def test_neon_accent_colors_are_not_png_subjects(self):
        """Live Cosmos spec said 'neon accents (cyan, magenta, electric blue)'.
        Job a7f86b12 queued those as photographs of colors."""
        line = (
            'Create a complete, production-ready website for a solar system '
            'tour company called "Cosmos Tours." The logo should be large. '
            "Use a dark color palette with neon accents "
            "(cyan, magenta, electric blue). Package section displaying "
            "tours to different planets (Mars, Jupiter, Saturn, Neptune, "
            "etc.). Each planet package should have a generated "
            "transparent PNG image of that planet."
        )
        paths = [row["output_path"] for row in plan_mixed_images(line)]
        self.assertEqual(
            paths,
            [
                "images/logo.png",
                "images/mars.png",
                "images/jupiter.png",
                "images/saturn.png",
                "images/neptune.png",
            ],
        )
        self.assertNotIn("images/cyan.png", paths)
        self.assertNotIn("images/magenta.png", paths)
        self.assertNotIn("images/electric-blue.png", paths)

    def test_attached_css_is_not_a_list_of_png_subjects(self):
        """Layout follow-up job 02940683 queued 1fr.png / auto-fit.png /
        135deg.png from stylesheet function arguments."""
        blob = (
            "the panels are long, can you make the panels wider not long\n"
            "styles.css\n"
            ".packages { display: grid; grid-template-columns: "
            "repeat(auto-fit, minmax(1fr, 1fr)); gap: 1.5rem; }\n"
            ".card { background: linear-gradient(135deg, var(--cyan), "
            "var(--magenta)); padding: 20px 40px; }\n"
            ".tier { transform: scale(0.8); opacity: 0.3; "
            "box-shadow: 0 0 20px rgba(0, 255, 255, 0.3); }\n"
            'img[src="images/logo.png"] { width: 180px; }\n'
            ".grid { grid-template-columns: repeat(2, 1fr); }\n"
        )
        paths = [row["output_path"] for row in plan_mixed_images(blob)]
        junk = (
            "images/1fr.png",
            "images/2.png",
            "images/20.png",
            "images/40.png",
            "images/0-8.png",
            "images/0.png",
            "images/255.png",
            "images/0-3.png",
            "images/135deg.png",
            "images/var-cyan.png",
            "images/auto-fit.png",
        )
        for path in junk:
            self.assertNotIn(path, paths)


    def test_transparent_ask_never_says_transparent_to_comfy(self):
        rewritten = rewrite_comfy_prompt("transparent PNG of a coffee cup")
        self.assertNotIn("transparent", rewritten.lower())
        self.assertNotIn(CHROMA_HEX, rewritten)
        self.assertNotIn(CUTOUT_TAIL.split(",")[0], rewritten)
        self.assertFalse(wants_transparent(rewritten))
        self.assertEqual(rewrite_comfy_prompt(rewritten), rewritten)
        hero = rewrite_comfy_prompt(
            "transparent website hero banner, purple dusk over dunes"
        )
        self.assertIn(SCENE_TAIL.split(",")[0], hero)
        self.assertNotIn(CHROMA_HEX, hero)
        self.assertNotIn(CUTOUT_TAIL.split(",")[0], hero)
        self.assertNotIn("transparent", hero.lower())
        self.assertFalse(wants_transparent(hero))

    def test_paren_name_list_queues_any_named_subjects(self):
        """Cabins, products, planets — same rule: names in parentheses."""
        line = (
            'create a website for a lodge called "Pine Lodge" with a logo '
            "and photos of the cabins (Oak, Pine, and Lake). Put files "
            "under pinelodge."
        )
        items = plan_mixed_images(line)
        paths = [row["output_path"] for row in items]
        self.assertEqual(
            paths,
            [
                "pinelodge/images/logo.png",
                "pinelodge/images/oak.png",
                "pinelodge/images/pine.png",
                "pinelodge/images/lake.png",
            ],
        )
        for row in items[1:]:
            self.assertNotIn("qwen-image:", row["prompt"].lower())
            self.assertIn("isolated object", row["prompt"].lower())

    def test_any_listed_subjects_queue_pngs_not_just_planets(self):
        line = (
            'create a website for a bakery called "Sweet Crust" with a logo '
            "and transparent PNG images of a croissant, a loaf of bread, "
            "and a cake. Put files under sweetcrust."
        )
        items = plan_mixed_images(line)
        paths = [row["output_path"] for row in items]
        self.assertEqual(
            paths,
            [
                "sweetcrust/images/logo.png",
                "sweetcrust/images/croissant.png",
                "sweetcrust/images/loaf-of-bread.png",
                "sweetcrust/images/cake.png",
            ],
        )
        logo = items[0]["prompt"].lower()
        self.assertTrue(logo.startswith("qwen-image:"))
        self.assertIn("sweet crust", logo)
        self.assertNotIn("transparent", logo)
        self.assertNotIn(CUTOUT_TAIL.split(",")[0], logo)
        for row in items[1:]:
            self.assertNotIn("qwen-image:", row["prompt"].lower())
            self.assertNotIn("transparent", row["prompt"].lower())
            self.assertNotIn(CUTOUT_TAIL.split(",")[0], row["prompt"])
            self.assertIn("isolated object", row["prompt"].lower())
            self.assertFalse(wants_qwen_image(row["prompt"]))

    def test_images_of_your_choice_does_not_invent_subjects(self):
        items = plan_mixed_images(
            "create a webpage and generate a header and logo images for it "
            "and a couple of other images on the page of your choice"
        )
        paths = [row["output_path"] for row in items]
        self.assertIn("images/logo.png", paths)
        self.assertTrue(set(paths) <= {"images/logo.png", "images/header.png"})

    def test_neutralize_strips_pillow_orders_from_cosmos_spec(self):
        spec = (
            'Create a complete, production-ready website for "Cosmos Tours." '
            "All images must be generated as transparent PNG files (not SVG) - "
            "create them using Python with PIL/Pillow. Deliverables: Complete "
            "HTML/CSS/JS and a Python script to generate the logo, planets, "
            "and icons."
        )
        cleaned = neutralize_local_image_script(spec)
        self.assertNotIn("PIL/Pillow", cleaned)
        self.assertNotIn("create them using Python", cleaned)
        self.assertNotIn("Python script to generate", cleaned)
        self.assertIn(GPU_PNG_NOTE, cleaned)
        self.assertEqual(neutralize_local_image_script("plain site spec"), "plain site spec")

    def test_parse_mixed_plan_json_reads_fenced_dests(self):
        from common.image_prompts import parse_mixed_plan_json, plan_from_extracted

        blob = (
            "```json\n"
            '{"images":[{"filename":"logo.png","subject":"logo that says Pine Lodge"},'
            '{"filename":"oak.png","subject":"photograph of an oak cabin"}]}\n'
            "```"
        )
        rows = parse_mixed_plan_json(blob)
        self.assertEqual([row["filename"] for row in rows], ["logo.png", "oak.png"])
        spec = (
            'create a website for a lodge called "Pine Lodge" with a logo. '
            "Put files under pinelodge."
        )
        paths = [
            row["output_path"] for row in plan_from_extracted(spec, rows)
        ]
        self.assertEqual(
            paths,
            ["pinelodge/images/logo.png", "pinelodge/images/oak.png"],
        )
        cut = plan_from_extracted(
            spec + " All images must be transparent PNG files.",
            [{"filename": "logo.png", "subject": "logo that says Pine Lodge"}],
        )
        self.assertNotIn(CUTOUT_TAIL, cut[0]["prompt"])
        self.assertNotIn("transparent", cut[0]["prompt"].lower())


class ImageTranslatorLogTests(unittest.TestCase):
    def test_logs_dest_prompts_when_enabled(self):
        from unittest import mock

        from common import gen_logging

        logged = []

        def fake_info(message, extra=None, details=None):
            logged.append((message, details or ""))

        with (
            mock.patch.object(gen_logging, "image_prompt_logging_on", return_value=True),
            mock.patch.object(gen_logging.xlogger, "info", side_effect=fake_info),
        ):
            gen_logging.log_image_translator(
                "generate",
                [
                    {
                        "output_path": "images/logo.png",
                        "prompt": "qwen-image: logo that says Cafe",
                    }
                ],
                source="classify",
                user_text="create a cafe site with a logo",
            )
        self.assertEqual(len(logged), 1)
        message, details = logged[0]
        self.assertIn("action=generate", message)
        self.assertIn("classify", message)
        self.assertIn("images/logo.png", details)
        self.assertIn("qwen-image: logo that says Cafe", details)
        self.assertIn("create a cafe site with a logo", details)

    def test_silent_when_option_is_off(self):
        from unittest import mock

        from common import gen_logging

        with (
            mock.patch.object(gen_logging, "image_prompt_logging_on", return_value=False),
            mock.patch.object(gen_logging.xlogger, "info") as info,
        ):
            gen_logging.log_image_translator(
                "generate",
                [{"output_path": "images/logo.png", "prompt": "logo"}],
            )
        info.assert_not_called()


if __name__ == "__main__":
    unittest.main()

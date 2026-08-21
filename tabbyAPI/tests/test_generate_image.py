import tempfile
import unittest
from pathlib import Path
from unittest import mock

import generate_image


class GenerateImageTests(unittest.TestCase):
    def test_run_generate_roundtrip(self):
        png = b"\x89PNG\r\n\x1a\n"
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            saved = folder / "generated-latest.png"
            saved.write_bytes(png)
            out = folder / "ui" / "icon.png"

            with (
                mock.patch.object(generate_image, "api_base", return_value="http://127.0.0.1:5000"),
                mock.patch.object(generate_image, "last_profile", return_value="qwen"),
                mock.patch.object(generate_image, "switch_to_comfy") as to_comfy,
                mock.patch.object(generate_image, "comfy_generate", return_value=png) as comfy_gen,
                mock.patch.object(generate_image, "save_generated_image", return_value=saved),
                mock.patch.object(generate_image, "switch_to_llm") as to_llm,
            ):
                result = generate_image.run_generate(
                    "login form with Submit",
                    output=out,
                    size="512x512",
                    qwen_image=True,
                )

            to_comfy.assert_called_once()
            comfy_gen.assert_called_once()
            self.assertEqual(comfy_gen.call_args.args[0], "qwen-image: login form with Submit")
            to_llm.assert_called_once()
            self.assertEqual(to_llm.call_args.args[0], "qwen")
            self.assertTrue(out.is_file())
            self.assertEqual(out.read_bytes(), png)
            self.assertEqual(result["path"], str(out))
            self.assertEqual(result["restored"], "qwen")
            self.assertFalse(result["stay_comfy"])

    def test_stay_comfy_skips_restore(self):
        png = b"\x89PNG\r\n\x1a\n"
        with tempfile.TemporaryDirectory() as raw:
            saved = Path(raw) / "generated-latest.png"
            saved.write_bytes(png)
            with (
                mock.patch.object(generate_image, "api_base", return_value="http://127.0.0.1:5000"),
                mock.patch.object(generate_image, "last_profile", return_value="glm"),
                mock.patch.object(generate_image, "switch_to_comfy"),
                mock.patch.object(generate_image, "comfy_generate", return_value=png),
                mock.patch.object(generate_image, "save_generated_image", return_value=saved),
                mock.patch.object(generate_image, "switch_to_llm") as to_llm,
            ):
                result = generate_image.run_generate("a red cube", stay_comfy=True)

            to_llm.assert_not_called()
            self.assertTrue(result["stay_comfy"])
            self.assertIsNone(result["restored"])
            self.assertEqual(result["path"], str(saved))

    def test_cli_help_runs(self):
        with mock.patch("sys.argv", ["generate_image.py", "--help"]):
            with self.assertRaises(SystemExit) as raised:
                generate_image.parse_args()
            self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()

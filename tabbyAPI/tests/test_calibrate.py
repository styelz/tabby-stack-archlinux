import tempfile
import unittest
from pathlib import Path

from calibrate import (
    DEPLOY_WAIT_RE,
    SWITCH_BLOCK_RE,
    agents_switch_block,
    cursor_wait_paragraph,
    deploy_wait_line,
    readme_times_paragraph,
    rewrite_agents_md,
)

SAMPLE = {
    "gpu": "Test GPU 8 GB",
    "qwen": {"ready_s": 12},
    "qwen35": {"ready_s": 118},
    "qwen36": {"ready_s": 95},
    "gemma": {"ready_s": 20},
    "gemma26": {"ready_s": 99},
    "glm": {"ready_s": 13},
    "comfy": {"ready_s": 6, "flux_s": 40, "qwen_image_s": 80},
    "llm": {"ready_s": 55},
}

PROFILES = {
    "qwen": {"seq": 262144, "vision": True},
    "qwen35": {"seq": 131072, "vision": True},
    "glm": {"seq": 65536, "vision": False},
}

AGENTS_STUB = """# notes

## Switch models

old table here

The GPU is exclusive: LLM or Comfy.

## Next
"""


class CalibrateDocsTests(unittest.TestCase):
    def test_switch_block_uses_measured_times(self):
        block = agents_switch_block(SAMPLE, "Test GPU 8 GB", PROFILES)
        self.assertIn("warm switches on this Test GPU 8 GB", block)
        self.assertIn("switch_times.json", block)
        self.assertNotIn("calibrate.py", block)
        self.assertIn("| `switch to qwen` | Daily coding, 9B | 262k | ~10 seconds |", block)
        self.assertIn("| `switch to qwen35` | Long or hard agent work | 131k | ~2 minutes |", block)
        self.assertIn("Thinking (vision off on Test GPU 8 GB)", block)
        self.assertIn("65k (model max)", block)
        self.assertIn("Flux ~40 seconds", block)
        self.assertIn("~55 seconds", block)
        self.assertIn("| `restart` | Bounce the API; last model reloads | — | ~55 seconds |", block)
        self.assertNotIn("switch to gemma", block)

    def test_rewrite_agents_preserves_following_section(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "AGENTS.md"
            path.write_text(AGENTS_STUB, encoding="utf-8")
            self.assertTrue(rewrite_agents_md(path, SAMPLE, "Test GPU 8 GB", PROFILES))
            text = path.read_text(encoding="utf-8")
            self.assertIn("## Switch models", text)
            self.assertIn("switch to qwen", text)
            self.assertIn("\n\nThe GPU is exclusive: LLM or Comfy.", text)
            self.assertIn("## Next", text)
            self.assertNotIn("old table here", text)
            self.assertNotIn("CLI:", text)
            self.assertEqual(len(SWITCH_BLOCK_RE.findall(text)), 1)

    def test_readme_and_cursor_paragraphs(self):
        readme = readme_times_paragraph(SAMPLE, "Test GPU 8 GB")
        self.assertTrue(readme.startswith("Warm switch times on this Test GPU 8 GB"))
        self.assertIn("qwen / gemma / `switch to llm` ~10s", readme)
        self.assertIn("qwen35 ~2 min", readme)
        self.assertIn("first Flux ~40s", readme)
        cursor = cursor_wait_paragraph(SAMPLE, "Test GPU 8 GB")
        self.assertIn("Warm wait on this Test GPU 8 GB", cursor)
        self.assertIn("qwen35 about 2 minutes", cursor)
        self.assertIn("Images come back as URLs on the same API host your editor or IDE already uses.", cursor)
        sample = (
            "- After `switch to …`, wait for the GPU (warm 12 GB 4070 Ti: qwen ~65s). "
            "GLM is thinking-only on 12 GB (vision off)."
        )
        self.assertTrue(DEPLOY_WAIT_RE.search(sample))
        line = deploy_wait_line(SAMPLE, "Test GPU 8 GB")
        self.assertTrue(line.startswith("- After `switch to …`, wait for the GPU"))
        self.assertIn("Test GPU 8 GB", line)


if __name__ == "__main__":
    unittest.main()

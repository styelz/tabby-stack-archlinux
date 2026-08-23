import unittest
from pathlib import Path
from types import SimpleNamespace

from common.gen_logging import tokenizer_bos_id


class TokenizerBosIdTests(unittest.TestCase):
    def test_none_tokenizer_after_unload(self):
        self.assertIsNone(tokenizer_bos_id(None))

    def test_reads_bos_token_id(self):
        self.assertEqual(tokenizer_bos_id(SimpleNamespace(bos_token_id=1)), 1)

    def test_missing_attribute(self):
        self.assertIsNone(tokenizer_bos_id(SimpleNamespace()))


class GenerateGenCleanupTests(unittest.TestCase):
    def test_generate_gen_finally_tolerates_unloaded_tokenizer(self):
        src = Path(__file__).resolve().parents[1].joinpath(
            "backends/exllamav3/model.py"
        ).read_text()
        self.assertIn("bos_token_id=tokenizer_bos_id(self.tokenizer)", src)
        self.assertNotIn("bos_token_id=self.tokenizer.bos_token_id", src)
        close_at = src.index("await self.generator.close()")
        tokenizer_at = src.index("self.tokenizer = None")
        self.assertLess(close_at, tokenizer_at)

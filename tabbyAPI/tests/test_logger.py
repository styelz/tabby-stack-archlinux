import unittest

from common.logger import console_width


class LoggerWidthTests(unittest.TestCase):
    def test_env_overrides_tty(self):
        self.assertEqual(console_width("200", isatty=True), 200)
        self.assertEqual(console_width("200", isatty=False), 200)

    def test_non_tty_defaults_wide(self):
        self.assertEqual(console_width("", isatty=False), 256)
        self.assertEqual(console_width(None, isatty=False), 256)

    def test_tty_auto_width(self):
        self.assertIsNone(console_width(None, isatty=True))
        self.assertIsNone(console_width("0", isatty=True))
        self.assertEqual(console_width("0", isatty=False), 256)

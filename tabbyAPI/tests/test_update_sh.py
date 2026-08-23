import unittest
from pathlib import Path


UPDATE_SH = Path(__file__).resolve().parents[2] / "update.sh"


class UpdateShRestartOptionTests(unittest.TestCase):
    def test_restart_flags_are_wired(self):
        src = UPDATE_SH.read_text()
        self.assertIn("[--restart|--no-restart]", src)
        self.assertIn("--restart) RESTART_API=1; shift ;;", src)
        self.assertIn("--no-restart) RESTART_API=0; shift ;;", src)
        self.assertIn("args+=(--restart)", src)
        self.assertIn("args+=(--no-restart)", src)
        self.assertIn('if [[ "$RESTART_API" == 1 ]]; then', src)
        self.assertIn("TABBY_UPDATE_RESTART", src)

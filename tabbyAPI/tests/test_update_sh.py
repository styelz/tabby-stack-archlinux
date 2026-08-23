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

    def test_git_update_always_offers_restart_button(self):
        src = UPDATE_SH.read_text()
        self.assertIn('--yes-label "Restart"', src)
        self.assertIn('--no-label "Skip"', src)
        self.assertIn("Already up to date. Restart tabbyapi anyway", src)
        self.assertIn("if ask_restart_api; then", src)
        self.assertNotIn("tabbyapi is not running, so it was not restarted.", src)
        self.assertNotIn(
            'if [[ "$pulled" -eq 0 ]]; then\n    ui_msg "Update git" "Already up to date. The API was not restarted.',
            src,
        )

    def test_origin_wrappers_win_when_pull_changes_them(self):
        src = UPDATE_SH.read_text()
        self.assertIn("Keeping origin/", src)
        self.assertIn("Restored local $wrap (unchanged on origin/", src)
        self.assertNotIn("Restored local install/update scripts", src)

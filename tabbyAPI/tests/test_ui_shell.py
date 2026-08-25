"""Jailed Code-mode shell: bwrap required, workspace bound at /work."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ui import shell
from ui import workspace


class ShellJailTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        workspace.set_workspaces_dir(Path(self._tmp.name))

    def tearDown(self):
        workspace.set_workspaces_dir(None)
        self._tmp.cleanup()

    def test_missing_bwrap_is_a_hard_error(self):
        with mock.patch("ui.shell.shutil.which", return_value=None):
            with self.assertRaises(shell.ShellError) as ctx:
                shell.bwrap_bin()
            self.assertIn("bubblewrap", str(ctx.exception).lower())

    def test_jail_binds_workspace_at_work(self):
        root = workspace.workspace_root("u", "c", create=True)
        with mock.patch("ui.shell.shutil.which", return_value="/usr/bin/bwrap"):
            cmd = shell.jail_command(root)
        self.assertEqual(cmd[0], "/usr/bin/bwrap")
        self.assertIn("--bind", cmd)
        bind_at = cmd.index("--bind")
        self.assertEqual(cmd[bind_at + 1], str(root.resolve()))
        self.assertEqual(cmd[bind_at + 2], "/work")
        self.assertIn("--chdir", cmd)
        self.assertEqual(cmd[cmd.index("--chdir") + 1], "/work")
        self.assertEqual(cmd[-1], "/bin/bash")
        self.assertNotIn(str(root.parent), cmd[bind_at + 2 :])


if __name__ == "__main__":
    unittest.main()

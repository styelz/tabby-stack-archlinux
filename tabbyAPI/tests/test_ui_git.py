"""Code-mode git helpers: listing skip, porcelain parse, path/branch checks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ui.git import (
    GitError,
    git_branch_name,
    looks_like_auth_failure,
    parse_log,
    parse_status_porcelain,
    redact_git_output,
    save_creds,
)
from ui import workspace


class SkipGitListingTests(unittest.TestCase):
    def test_skips_git_dir_and_credential_names(self):
        self.assertTrue(workspace.skip_listing_rel(".git/config"))
        self.assertTrue(workspace.skip_listing_rel("repo/.git/objects/pack/foo"))
        self.assertTrue(workspace.skip_listing_rel(".gitconfig"))
        self.assertTrue(workspace.skip_listing_rel(".git-credentials"))
        self.assertFalse(workspace.skip_listing_rel("src/app.js"))
        self.assertFalse(workspace.skip_listing_rel("gitignore"))

    def test_iterators_omit_git_objects(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "readme.md").write_text("hi", encoding="utf-8")
            git = root / ".git" / "objects"
            git.mkdir(parents=True)
            (git / "pack").write_text("blob", encoding="utf-8")
            (root / ".gitconfig").write_text("x", encoding="utf-8")
            files = [path.name for path in workspace._iter_files(root)]
            dirs = [path.name for path in workspace._iter_dirs(root)]
            self.assertEqual(files, ["readme.md"])
            self.assertNotIn(".git", dirs)
            self.assertNotIn(".gitconfig", files)


class GitPorcelainTests(unittest.TestCase):
    def test_status_branch_ahead_behind_and_files(self):
        text = "\n".join(
            [
                "## main...origin/main [ahead 1, behind 2]",
                "M  staged.py",
                " M work.py",
                "?? new.py",
                'R  "old name.py" -> "new name.py"',
            ]
        )
        parsed = parse_status_porcelain(text)
        self.assertEqual(parsed["branch"], "main")
        self.assertEqual(parsed["upstream"], "origin/main")
        self.assertEqual(parsed["ahead"], 1)
        self.assertEqual(parsed["behind"], 2)
        paths = [row["path"] for row in parsed["files"]]
        self.assertEqual(paths, ["staged.py", "work.py", "new.py", "new name.py"])
        self.assertTrue(parsed["files"][0]["staged"])
        self.assertTrue(parsed["files"][1]["unstaged"])
        self.assertFalse(parsed["files"][2]["staged"])

    def test_log_rows(self):
        rows = parse_log("abc\tabc123\tAda\t1700000000\tFix login\n")
        self.assertEqual(rows[0]["short"], "abc123")
        self.assertEqual(rows[0]["subject"], "Fix login")
        self.assertEqual(rows[0]["ts"], 1700000000)

    def test_branch_names(self):
        self.assertEqual(git_branch_name("feature/login"), "feature/login")
        with self.assertRaises(GitError):
            git_branch_name("-bad")
        with self.assertRaises(GitError):
            git_branch_name("has space")
        with self.assertRaises(GitError):
            git_branch_name("foo..bar")
        with self.assertRaises(GitError):
            git_branch_name("HEAD")

    def test_redact_and_auth(self):
        raw = "fatal: could not read Username for 'https://git:secret@github.com/x.git'"
        self.assertIn("https://***@", redact_git_output(raw))
        self.assertNotIn("secret", redact_git_output(raw))
        self.assertTrue(looks_like_auth_failure("could not read Username for 'https://x': terminal prompts disabled"))
        self.assertFalse(looks_like_auth_failure("nothing to commit"))


class GitCredsHostTests(unittest.TestCase):
    def test_save_creds_rejects_bad_host_and_writes_store_line(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace.set_workspaces_dir(Path(raw))
            try:
                with self.assertRaises(GitError):
                    save_creds("alice", "c1", "tok", "localhost")
                save_creds("alice", "c1", "ghs_exampletoken", "github.com")
                path = Path(raw) / "alice" / "c1.codebox" / "git-credentials"
                text = path.read_text(encoding="ascii")
                self.assertTrue(text.startswith("https://git:"))
                self.assertIn("@github.com", text)
                self.assertNotIn("\n\n", text)
            finally:
                workspace.set_workspaces_dir(None)


class FindRepoTests(unittest.TestCase):
    def test_finds_git_dir_at_workspace_root(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".git").mkdir()
            (root / "README.md").write_text("x", encoding="utf-8")
            from ui.git import find_repo_on_disk

            self.assertEqual(find_repo_on_disk(root), "")

    def test_finds_single_child_repo(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dest = root / "tabby-stack"
            dest.mkdir()
            (dest / ".git").mkdir()
            from ui.git import find_repo_on_disk

            self.assertEqual(find_repo_on_disk(root), "tabby-stack")

    def test_status_stays_a_repo_when_git_command_fails(self):
        from unittest import mock
        from ui.git import GitError, git_status

        with tempfile.TemporaryDirectory() as raw:
            workspace.set_workspaces_dir(Path(raw))
            try:
                root = workspace.workspace_root("alice", "c1", create=True, box=False)
                (root / ".git").mkdir()
                with mock.patch("ui.git._run_git", side_effect=GitError("docker down")):
                    data = git_status("alice", "c1")
                self.assertTrue(data["repo"])
                self.assertEqual(data["root"], "")
                self.assertIn("docker down", data["error"])
            finally:
                workspace.set_workspaces_dir(None)

    def test_git_cmd_quotes_safe_directory(self):
        from ui.git import _git_cmd

        cmd = _git_cmd("", ["status", "--porcelain=v1", "-b"])
        self.assertIn("safe.directory=*", cmd)
        self.assertIn("'safe.directory=*'", cmd)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import gallery_owners
from ui import auth, chats, users


class UiUsersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        users.set_users_path(Path(self.tmp.name) / "ui_users.json")
        auth.clear_sessions()
        auth.set_authenticator(None)

    def tearDown(self):
        auth.set_authenticator(None)
        auth.clear_sessions()
        users.set_users_path(None)
        self.tmp.cleanup()

    def test_create_and_verify(self):
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            created = users.create_user("alice", "secret123")
        self.assertEqual(created["username"], "alice")
        self.assertTrue(users.verify_extra_user("alice", "secret123"))
        self.assertFalse(users.verify_extra_user("alice", "wrong"))
        self.assertEqual(users.match_password("secret123"), "alice")
        self.assertIsNone(users.match_password("wrong"))
        self.assertEqual(users.list_users()[0]["username"], "alice")

    def test_duplicate_and_admin_name_rejected(self):
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            users.create_user("alice", "secret123")
            with self.assertRaises(ValueError):
                users.create_user("Alice", "secret123")
            with self.assertRaises(ValueError):
                users.create_user("tabby", "secret123")

    def test_delete_and_reset(self):
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            users.create_user("bob", "secret123")
            users.set_password("bob", "newsecret")
            self.assertTrue(users.verify_extra_user("bob", "newsecret"))
            users.delete_user("bob")
        self.assertFalse(users.verify_extra_user("bob", "newsecret"))
        with self.assertRaises(KeyError):
            users.delete_user("bob")


class UiAuthExtraUserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        users.set_users_path(Path(self.tmp.name) / "ui_users.json")
        auth.clear_sessions()
        auth.set_authenticator(None)

    def tearDown(self):
        auth.set_authenticator(None)
        auth.clear_sessions()
        users.set_users_path(None)
        self.tmp.cleanup()

    def test_extra_user_does_not_call_pam(self):
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            users.create_user("alice", "secret123")
            with mock.patch.object(auth, "_pam_authenticate") as pam:
                self.assertTrue(auth.authenticate_user("alice", "secret123"))
                pam.assert_not_called()
                self.assertFalse(auth.authenticate_user("alice", "nope"))
                pam.assert_not_called()

    def test_unknown_user_does_not_call_pam(self):
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            with mock.patch.object(auth, "_pam_authenticate") as pam:
                self.assertFalse(auth.authenticate_user("carol", "secret123"))
                pam.assert_not_called()

    def test_session_is_admin_only_for_stack_user(self):
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            self.assertTrue(auth.is_admin_username("tabby"))
            self.assertFalse(auth.is_admin_username("alice"))
            token = auth.create_session("alice")
            self.assertEqual(auth.validate_session(token), "alice")
            auth.destroy_sessions_for_user("alice")
            self.assertIsNone(auth.validate_session(token))


class UiChatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        chats.set_chats_dir(Path(self.tmp.name))

    def tearDown(self):
        chats.set_chats_dir(None)
        self.tmp.cleanup()

    def test_isolation(self):
        chats.save_store(
            "alice",
            {
                "version": 1,
                "activeId": "c1",
                "chats": [
                    {
                        "id": "c1",
                        "title": "Hi",
                        "updatedAt": 1,
                        "messages": [{"role": "user", "content": "hello"}],
                    }
                ],
            },
        )
        alice = chats.load_store("alice")
        bob = chats.load_store("bob")
        self.assertEqual(len(alice["chats"]), 1)
        self.assertEqual(alice["chats"][0]["title"], "Hi")
        self.assertEqual(bob["chats"], [])
        chats.delete_store("alice")
        self.assertEqual(chats.load_store("alice")["chats"], [])

    def test_chat_count_skips_empty(self):
        chats.save_store(
            "alice",
            {
                "version": 1,
                "activeId": "c1",
                "chats": [
                    {
                        "id": "c1",
                        "title": "Hi",
                        "updatedAt": 1,
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    {
                        "id": "c2",
                        "title": "New chat",
                        "updatedAt": 2,
                        "messages": [{"role": "system", "content": "Console chat."}],
                    },
                ],
            },
        )
        self.assertEqual(chats.chat_count("alice"), 1)
        self.assertEqual(chats.chat_count("bob"), 0)

    def test_append_flight_assistant_keeps_steps(self):
        chats.save_store(
            "alice",
            {
                "version": 1,
                "activeId": "c1",
                "chats": [
                    {
                        "id": "c1",
                        "title": "Hi",
                        "updatedAt": 1,
                        "messages": [{"role": "user", "content": "hello"}],
                    }
                ],
            },
        )
        chats.append_flight_assistant(
            "alice",
            "c1",
            content="Wrote index.html",
            reasoning="thinking",
            elapsed_s=3,
            status_label="Replied",
            steps=[{"type": "tool", "name": "Write", "label": "Writing index.html"}],
        )
        store = chats.load_store("alice")
        last = store["chats"][0]["messages"][-1]
        self.assertEqual(last["role"], "assistant")
        self.assertEqual(last["content"], "Wrote index.html")
        self.assertEqual(last["steps"][0]["name"], "Write")


class UiUserUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name)
        users.set_users_path(folder / "ui_users.json")
        chats.set_chats_dir(folder / "chats")
        gallery_owners.set_owners_path(folder / "gallery_owners.json")
        self._dir_patch = mock.patch("common.gpu_mode.GENERATED_DIR", folder)
        self._dir_patch.start()
        auth.clear_sessions()
        auth.set_authenticator(None)

    def tearDown(self):
        self._dir_patch.stop()
        auth.set_authenticator(None)
        auth.clear_sessions()
        gallery_owners.set_owners_path(None)
        chats.set_chats_dir(None)
        users.set_users_path(None)
        self.tmp.cleanup()

    def test_login_counts_and_accounts(self):
        from common import gallery_owners

        folder = Path(self.tmp.name)
        (folder / "generated-admin.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (folder / "generated-alice.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        gallery_owners.record_owner("generated-alice.png", "alice")
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            users.create_user("alice", "secret123")
            self.assertEqual(users.record_login("alice"), 1)
            self.assertEqual(users.record_login("alice"), 2)
            self.assertEqual(users.record_login("tabby"), 1)
            chats.save_store(
                "alice",
                {
                    "version": 1,
                    "activeId": "c1",
                    "chats": [
                        {
                            "id": "c1",
                            "title": "Hi",
                            "updatedAt": 1,
                            "messages": [{"role": "user", "content": "hello"}],
                        }
                    ],
                },
            )
            rows = {row["username"]: row for row in users.list_accounts()}
        self.assertIn("tabby", rows)
        self.assertTrue(rows["tabby"]["is_admin"])
        self.assertEqual(rows["tabby"]["logins"], 1)
        self.assertEqual(rows["tabby"]["images"], 1)
        self.assertEqual(rows["alice"]["logins"], 2)
        self.assertEqual(rows["alice"]["chats"], 1)
        self.assertEqual(rows["alice"]["images"], 1)
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            users.delete_user("alice")
            rows = {row["username"]: row for row in users.list_accounts()}
        self.assertNotIn("alice", rows)
        self.assertEqual(users.record_login("alice"), 1)


class UiUsersPageTests(unittest.TestCase):
    def test_table_has_usage_columns(self):
        src = (Path(__file__).resolve().parents[1] / "ui" / "static" / "users.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("Logins", src)
        self.assertIn("Chats", src)
        self.assertIn("Images", src)
        self.assertIn("user.logins", src)
        self.assertIn("user.chats", src)
        self.assertIn("user.images", src)

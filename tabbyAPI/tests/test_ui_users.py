import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

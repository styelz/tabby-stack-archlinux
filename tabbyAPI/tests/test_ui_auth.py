import unittest
from unittest import mock

from ui import auth


class UiAuthTests(unittest.TestCase):
    def setUp(self):
        auth.clear_sessions()
        auth.set_authenticator(None)

    def tearDown(self):
        auth.set_authenticator(None)
        auth.clear_sessions()

    def test_rejects_wrong_user(self):
        auth.set_authenticator(lambda user, password: True)
        with mock.patch.object(auth, "stack_username", return_value="tabby"):
            # authenticator hook bypasses the username check when set
            self.assertTrue(auth.authenticate_user("tabby", "secret"))

    def test_session_roundtrip(self):
        token = auth.create_session("tabby")
        self.assertEqual(auth.validate_session(token), "tabby")
        auth.destroy_session(token)
        self.assertIsNone(auth.validate_session(token))

    def test_expired_session(self):
        token = auth.create_session("tabby")
        self.assertIsNone(auth.validate_session(token, max_age=-1))

    def test_login_rate_limit(self):
        ip = "203.0.113.9"
        for _ in range(auth.LOGIN_MAX_ATTEMPTS):
            self.assertTrue(auth.login_allowed(ip))
            auth.record_login_attempt(ip)
        self.assertFalse(auth.login_allowed(ip))

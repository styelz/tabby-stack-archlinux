"""Console chat store keeps Chat and Code conversations separate."""

from __future__ import annotations

import unittest

from ui.chats import normalize_store


class ChatStoreNormalizeTests(unittest.TestCase):
    def test_keeps_last_chat_per_mode(self):
        store = normalize_store(
            {
                "activeId": "c1",
                "chats": [
                    {"id": "c1", "mode": "chat", "title": "Hi", "messages": []},
                    {"id": "p1", "mode": "code", "title": "Page", "messages": []},
                ],
                "lastByMode": {"chat": "c1", "code": "p1"},
            }
        )
        self.assertEqual(store["lastByMode"], {"chat": "c1", "code": "p1"})
        self.assertEqual([c["mode"] for c in store["chats"]], ["chat", "code"])

    def test_drops_last_id_when_mode_does_not_match(self):
        store = normalize_store(
            {
                "chats": [
                    {"id": "c1", "mode": "chat", "title": "Hi", "messages": []},
                ],
                "lastByMode": {"chat": "missing", "code": "c1"},
            }
        )
        self.assertEqual(store["lastByMode"], {"chat": "", "code": ""})


if __name__ == "__main__":
    unittest.main()

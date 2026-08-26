"""Console chat store keeps Chat and Code conversations separate."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ui import chats, workspace
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

    def test_keeps_nested_parent_id(self):
        store = normalize_store(
            {
                "chats": [
                    {"id": "w1", "mode": "code", "title": "App", "messages": []},
                    {"id": "t1", "mode": "code", "parentId": "w1", "title": "Fix", "messages": []},
                ]
            }
        )
        by_id = {chat["id"]: chat for chat in store["chats"]}
        self.assertEqual(by_id["w1"]["parentId"], "")
        self.assertEqual(by_id["t1"]["parentId"], "w1")

    def test_drops_orphan_nested_chats(self):
        store = normalize_store(
            {
                "chats": [
                    {
                        "id": "t1",
                        "mode": "code",
                        "parentId": "missing",
                        "title": "Fix",
                        "messages": [],
                    }
                ]
            }
        )
        self.assertEqual(store["chats"], [])

    def test_strips_parent_id_on_chat_mode(self):
        store = normalize_store(
            {
                "chats": [
                    {"id": "c1", "mode": "chat", "parentId": "w1", "title": "Hi", "messages": []}
                ]
            }
        )
        self.assertEqual(store["chats"][0]["parentId"], "")

    def test_drops_second_level_nesting(self):
        store = normalize_store(
            {
                "chats": [
                    {"id": "w1", "mode": "code", "messages": []},
                    {"id": "t1", "mode": "code", "parentId": "w1", "messages": []},
                    {"id": "t2", "mode": "code", "parentId": "t1", "messages": []},
                ]
            }
        )
        self.assertEqual({chat["id"] for chat in store["chats"]}, {"w1", "t1"})


class ChatStoreSaveWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name)
        chats.set_chats_dir(folder / "chats")
        workspace.set_workspaces_dir(folder / "ws")

    def tearDown(self):
        chats.set_chats_dir(None)
        workspace.set_workspaces_dir(None)
        self.tmp.cleanup()

    def test_dropping_nested_chat_keeps_workspace_files(self):
        workspace.write_text("u", "w1", "index.html", "<p>hi</p>")
        chats.save_store(
            "u",
            {
                "activeId": "w1",
                "chats": [
                    {
                        "id": "w1",
                        "mode": "code",
                        "title": "App",
                        "messages": [{"role": "user", "content": "x"}],
                    },
                    {
                        "id": "t1",
                        "mode": "code",
                        "parentId": "w1",
                        "title": "Fix",
                        "messages": [{"role": "user", "content": "y"}],
                    },
                ],
            },
        )
        chats.save_store(
            "u",
            {
                "activeId": "w1",
                "chats": [
                    {
                        "id": "w1",
                        "mode": "code",
                        "title": "App",
                        "messages": [{"role": "user", "content": "x"}],
                    }
                ],
            },
        )
        self.assertEqual(workspace.read_text("u", "w1", "index.html"), "<p>hi</p>")
        loaded = chats.load_store("u")
        self.assertEqual([chat["id"] for chat in loaded["chats"]], ["w1"])

    def test_dropping_workspace_root_deletes_files(self):
        workspace.write_text("u", "w1", "index.html", "<p>hi</p>")
        chats.save_store(
            "u",
            {
                "chats": [
                    {
                        "id": "w1",
                        "mode": "code",
                        "title": "App",
                        "messages": [{"role": "user", "content": "x"}],
                    }
                ]
            },
        )
        chats.save_store("u", {"chats": []})
        self.assertFalse(workspace.has_files("u", "w1"))


if __name__ == "__main__":
    unittest.main()

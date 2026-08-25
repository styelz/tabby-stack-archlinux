"""UI console chat stop / queue / steer. Keep in sync with ui/static/chat.js."""

from __future__ import annotations

import unittest
from pathlib import Path

CHAT_JS = Path(__file__).resolve().parents[1] / "ui" / "static" / "chat.js"
CHAT_CSS = Path(__file__).resolve().parents[1] / "ui" / "static" / "styles.css"


def compose_action(in_flight: bool, typed: str, queued: str) -> tuple[str, bool]:
    text = (typed or "").strip()
    has_queue = bool((queued or "").strip())
    if not in_flight:
        return "send", False
    if text:
        return "queue", has_queue
    return "stop", has_queue


class ChatComposeActionTests(unittest.TestCase):
    def test_idle_send_never_steers(self):
        self.assertEqual(compose_action(False, "hello", ""), ("send", False))
        self.assertEqual(compose_action(False, "", "later"), ("send", False))

    def test_in_flight_empty_input_is_stop(self):
        self.assertEqual(compose_action(True, "", ""), ("stop", False))
        self.assertEqual(compose_action(True, "  ", "queued"), ("stop", True))

    def test_in_flight_typed_text_queues(self):
        self.assertEqual(compose_action(True, "more detail", ""), ("queue", False))
        self.assertEqual(compose_action(True, "instead", "old"), ("queue", True))


class ChatJsStopQueueSteerTests(unittest.TestCase):
    def setUp(self):
        self.src = CHAT_JS.read_text(encoding="utf-8")

    def test_compose_helper_matches_python_matrix(self):
        self.assertIn("function tabbyChatComposeAction(inFlight, typed, queued)", self.src)
        self.assertIn('mode: "send"', self.src)
        self.assertIn('mode: "queue"', self.src)
        self.assertIn('mode: "stop"', self.src)
        self.assertIn("showSteer", self.src)

    def test_send_button_becomes_stop_during_session(self):
        self.assertIn('label: "Stop"', self.src)
        self.assertIn("abortSession(\"stop\")", self.src)
        self.assertIn("classList.toggle(\"is-stop\"", self.src)
        self.assertIn("chat-stop-icon", self.src)

    def test_abort_controller_cancels_fetch(self):
        self.assertIn("new AbortController()", self.src)
        self.assertIn("signal: abortController.signal", self.src)
        self.assertIn('err.name === "AbortError"', self.src)
        self.assertNotRegex(self.src, r"if \(inFlight\) return;")

    def test_typed_text_during_session_is_queued(self):
        self.assertIn("function queueFollowup(text)", self.src)
        self.assertIn("if (inFlight)", self.src)
        self.assertIn("queueFollowup(text)", self.src)
        self.assertIn('label: "Queue"', self.src)
        self.assertIn("id=\"chat-queue\"", self.src)

    def test_queued_message_can_steer(self):
        self.assertIn("id=\"chat-steer\"", self.src)
        self.assertIn("abortSession(\"steer\")", self.src)
        self.assertIn('if (stopKind === "steer")', self.src)
        self.assertIn("showSteer: hasQueue", self.src)

    def test_empty_stop_does_not_keep_working_bubble(self):
        self.assertIn("working.discard()", self.src)
        self.assertIn("function abortSession(kind)", self.src)

    def test_finished_reply_keeps_elapsed_time(self):
        self.assertIn("item.elapsed_s = elapsedSec", self.src)
        self.assertIn("item.status_label = statusLabel", self.src)
        self.assertNotIn("Replied in ${elapsed}", self.src)
        self.assertIn("timeEl.textContent = seconds != null ? TabbyUI.formatDuration(seconds) : \"\"", self.src)

    def test_mode_toggle_opens_a_separate_conversation(self):
        self.assertIn("function chatForMode(mode)", self.src)
        self.assertIn("function setChatMode(mode)", self.src)
        self.assertNotIn("chat.mode = next", self.src)
        self.assertIn("chatMode(chat) === mode", self.src)
        self.assertIn("lastByMode", self.src)

    def test_sidebar_row_actions_overlay_the_cell(self):
        css = CHAT_CSS.read_text(encoding="utf-8")
        self.assertIn(".chat-nav-tools {", css)
        self.assertIn(".chat-file-tools {", css)
        self.assertIn("position: absolute", css)
        self.assertNotRegex(css, r"\.chat-nav \{[^}]*grid-template-columns: 18px minmax\(0, 1fr\) auto")
        self.assertNotRegex(css, r"\.chat-file \{[^}]*grid-template-columns: minmax\(0, 1fr\) auto auto auto auto")
        self.assertIn('class="chat-file-tools"', self.src)

    def test_dirty_tabs_are_stashed_per_chat(self):
        self.assertIn("let tabsByChat", self.src)
        self.assertIn("function stashCurrentTabs()", self.src)
        self.assertIn("function switchWorkspaceTabs(chatId)", self.src)
        self.assertIn("function warnDirtyUnload(event)", self.src)
        self.assertIn("anyDirtyTabs()", self.src)

    def test_optimizing_status_refreshes_files(self):
        self.assertIn("Writing|Editing|Deleting|Optimizing|Renaming", self.src)

    def test_files_overflow_and_history_collapse(self):
        self.assertIn('id="chat-files-more"', self.src)
        self.assertIn('data-files-more="refresh"', self.src)
        self.assertIn('id="chat-files-history-toggle"', self.src)
        self.assertIn("function setHistoryOpen(open)", self.src)
        css = CHAT_CSS.read_text(encoding="utf-8")
        self.assertIn(".chat-files-history.is-collapsed", css)
        self.assertIn(".chat-files.is-drop", css)

    def test_find_in_chat_bar(self):
        self.assertIn('id="chat-find"', self.src)
        self.assertIn("function openFind(seed)", self.src)
        self.assertIn("function jumpSidebarSearch()", self.src)
        self.assertIn("function paintFindHits()", self.src)


if __name__ == "__main__":
    unittest.main()


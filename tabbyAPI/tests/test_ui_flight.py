"""Console flight SSE ingest for Code agent steps."""

from __future__ import annotations

import json
import unittest

from ui.flight import ConsoleFlight, get_flight, register_flight, reset_for_tests


class FlightIngestTests(unittest.TestCase):
    def test_ingest_agent_step_and_demote(self):
        flight = ConsoleFlight("u", "c", "code", "hi")
        flight.ingest(
            b'data: {"choices":[{"delta":{"content":"draft plan"}}]}\n\n'
        )
        self.assertEqual(flight.assembled, "draft plan")
        flight.ingest(b": tabby-agent-step: {\"type\":\"demote\"}\n\n")
        self.assertEqual(flight.assembled, "")
        self.assertEqual(flight.steps[0]["type"], "said")
        self.assertEqual(flight.steps[0]["content"], "draft plan")
        step = {
            "type": "tool",
            "name": "Write",
            "label": "Writing a.html",
            "args": {"path": "a.html"},
            "result": "Wrote a.html",
        }
        flight.ingest(
            f": tabby-agent-step: {json.dumps(step, separators=(',', ':'))}\n\n".encode()
        )
        self.assertEqual(flight.steps[-1]["name"], "Write")
        flight.ingest(
            b'data: {"choices":[{"delta":{"content":"Wrote a.html"}}]}\n\n'
        )
        self.assertEqual(flight.assembled, "Wrote a.html")
        flight.ingest(
            b'data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}\n\n'
        )
        self.assertEqual(flight.reasoning, "hmm")


class FlightRegisterTests(unittest.TestCase):
    def setUp(self):
        reset_for_tests()

    def tearDown(self):
        reset_for_tests()

    def test_register_does_not_abort_other_conversation(self):
        first = ConsoleFlight("u", "chat-a", "chat", "draw a cat")
        second = ConsoleFlight("u", "chat-b", "chat", "hello")
        register_flight(first)
        register_flight(second)
        self.assertFalse(first.abort_event.is_set())
        self.assertIs(get_flight("u"), second)

    def test_register_aborts_same_conversation(self):
        first = ConsoleFlight("u", "chat-a", "chat", "one")
        second = ConsoleFlight("u", "chat-a", "chat", "two")
        register_flight(first)
        register_flight(second)
        self.assertTrue(first.abort_event.is_set())

    def test_register_aborts_when_previous_has_no_chat_id(self):
        first = ConsoleFlight("u", "", "chat", "one")
        second = ConsoleFlight("u", "chat-b", "chat", "two")
        register_flight(first)
        register_flight(second)
        self.assertTrue(first.abort_event.is_set())

    def test_abort_is_scoped_to_chat_id(self):
        from ui.flight import abort_flight

        first = ConsoleFlight("u", "chat-a", "chat", "one")
        second = ConsoleFlight("u", "chat-b", "chat", "two")
        register_flight(first)
        register_flight(second)
        self.assertTrue(abort_flight("u", "chat-a"))
        self.assertTrue(first.abort_event.is_set())
        self.assertFalse(second.abort_event.is_set())
        self.assertTrue(abort_flight("u", "chat-b"))
        self.assertTrue(second.abort_event.is_set())

    def test_abort_other_chat_does_not_stop_current(self):
        from ui.flight import abort_flight

        flight = ConsoleFlight("u", "chat-b", "chat", "hello")
        register_flight(flight)
        self.assertFalse(abort_flight("u", "chat-a"))
        self.assertFalse(flight.abort_event.is_set())

    def test_get_flight_by_chat_id_after_replacement(self):
        first = ConsoleFlight("u", "chat-a", "chat", "one")
        second = ConsoleFlight("u", "chat-b", "chat", "two")
        register_flight(first)
        register_flight(second)
        self.assertIs(get_flight("u"), second)
        self.assertIs(get_flight("u", "chat-a"), first)
        self.assertIs(get_flight("u", "chat-b"), second)
        self.assertIsNone(get_flight("u", "missing"))


if __name__ == "__main__":
    unittest.main()

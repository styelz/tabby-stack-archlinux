"""Console flight SSE ingest for Code agent steps."""

from __future__ import annotations

import json
import unittest

from ui.flight import ConsoleFlight


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


if __name__ == "__main__":
    unittest.main()

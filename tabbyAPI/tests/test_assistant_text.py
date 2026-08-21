import asyncio
import json
import unittest

from common.assistant_text import (
    strip_apology_sse,
    strip_leading_apology,
    strip_response_apologies,
)
from endpoints.OAI.types.chat_completion import (
    ChatCompletionMessage,
    ChatCompletionRespChoice,
    ChatCompletionResponse,
)


class AssistantTextTests(unittest.TestCase):
    def test_strips_copilot_retry_apology(self):
        text = (
            "I apologize for the repeated attempts. "
            "Let me create the solar system tours website."
        )
        self.assertEqual(
            strip_leading_apology(text),
            "Let me create the solar system tours website.",
        )
        stacked = (
            "I apologize for the repeated errors. "
            "I'm sorry for the terminal errors. "
            "Creating the page now."
        )
        self.assertEqual(strip_leading_apology(stacked), "Creating the page now.")
        self.assertEqual(
            strip_leading_apology("I'll create the page now."),
            "I'll create the page now.",
        )

    def test_response_content_is_cleaned(self):
        response = ChatCompletionResponse(
            model="gpt-4o",
            choices=[
                ChatCompletionRespChoice(
                    finish_reason="stop",
                    message=ChatCompletionMessage(
                        role="assistant",
                        content="I apologize for the repeated terminal errors. mkdir now.",
                    ),
                )
            ],
        )
        strip_response_apologies(response)
        self.assertEqual(response.choices[0].message.content, "mkdir now.")

    def test_stream_drops_split_apology(self):
        chunks = [
            json.dumps(
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [
                        {"index": 0, "delta": {"content": "I apologize for the "}}
                    ],
                }
            ),
            json.dumps(
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": "repeated attempts. Let me create the site."
                            },
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            ),
            "[DONE]",
        ]

        async def src():
            for chunk in chunks:
                yield chunk

        async def collect():
            return [item async for item in strip_apology_sse(src())]

        out = asyncio.run(collect())
        texts = []
        for item in out:
            if item == "[DONE]":
                continue
            data = json.loads(item)
            text = data["choices"][0].get("delta", {}).get("content")
            if text:
                texts.append(text)
        self.assertEqual("".join(texts), "Let me create the site.")
        self.assertEqual(out[-1], "[DONE]")


if __name__ == "__main__":
    unittest.main()

import asyncio
import unittest
from unittest import mock

from images import chat as images_chat
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest


class ConsoleImageChatTests(unittest.TestCase):
    def test_handle_accepts_console_flag(self):
        self.assertIn("console", images_chat.handle.__code__.co_varnames)

    def test_console_generate_skips_file_tools(self):
        async def go():
            data = ChatCompletionRequest(
                messages=[ChatCompletionMessage(role="user", content="draw a red cube")]
            )
            plan = mock.Mock(
                action="generate",
                items=[{"prompt": "red cube", "output_path": "images/a.png"}],
            )
            started = mock.Mock(id="job-ui")
            with (
                mock.patch.object(
                    images_chat, "classify_image_turn", new=mock.AsyncMock(return_value=plan)
                ),
                mock.patch.object(images_chat, "active_mcp_image_job", return_value=None),
                mock.patch.object(
                    images_chat, "_start_mixed_job", new=mock.AsyncMock(return_value=started)
                ) as start,
                mock.patch.object(images_chat, "_write_site_code", new=mock.AsyncMock()) as write,
                mock.patch.object(
                    images_chat, "_hold_then_reply", new=mock.AsyncMock(return_value="held")
                ) as hold,
            ):
                result = await images_chat.handle(
                    data, api_base="http://x", llm_ready=True, console=True
                )
            write.assert_not_called()
            start.assert_awaited()
            hold.assert_awaited()
            self.assertEqual(result, "held")

        asyncio.run(go())

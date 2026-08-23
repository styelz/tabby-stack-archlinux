import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from images import chat as images_chat
from ui.chat import completion_request_from_payload
from ui.manager import sanitize_chat_payload
from common.phrase_switch import (
    image_ready_response,
    is_help_request,
    is_list_request,
    is_restart_request,
    requested_profile,
)
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
            self.assertTrue(hold.await_args.kwargs.get("console"))
            self.assertFalse(hold.await_args.kwargs.get("mixed"))
            self.assertEqual(result, "held")

        asyncio.run(go())


class ConsoleImageReplyTests(unittest.TestCase):
    def _job(self, **kwargs):
        url = kwargs.pop(
            "url",
            "https://gpu.example/v1/images/generated-20260824-060727-122943.png",
        )
        defaults = dict(
            id="748b6eef-f8ac-4529-a6b3-be3c7ffd1730",
            error="",
            restore=True,
            wait_text=(
                "About 3 minutes to render (Flux), then about 65 seconds "
                "to reload the coding model."
            ),
            items=[],
            url=url,
        )
        defaults.update(kwargs)
        url = defaults.pop("url")
        job = SimpleNamespace(**defaults)
        return job, url

    def test_console_reply_hides_job_jargon(self):
        data = ChatCompletionRequest(
            messages=[ChatCompletionMessage(role="user", content="create an image of c3po and r2d2")]
        )
        job, url = self._job()
        with mock.patch.object(
            images_chat, "living_download_pairs", return_value=[(url, "images/generated.png")]
        ):
            response = images_chat._url_response(
                data, job, "https://gpu.example/v1", console=True
            )
        text = response.choices[0].message.content
        self.assertNotIn("tabby-image-job:", text)
        self.assertNotIn(job.id, text)
        self.assertNotIn("image(s) from this turn", text)
        self.assertNotIn("Another picture:", text)
        self.assertNotIn("This picture:", text)
        self.assertIn("Here's the picture", text)
        self.assertIn(f"![]({url})", text)
        self.assertEqual(text.count(url), 1)

    def test_ide_reply_still_stamps_job(self):
        data = ChatCompletionRequest(
            messages=[ChatCompletionMessage(role="user", content="generate an image of a cube")]
        )
        job, url = self._job()
        with mock.patch.object(
            images_chat, "living_download_pairs", return_value=[(url, "images/generated.png")]
        ):
            response = images_chat._url_response(
                data, job, "https://gpu.example/v1", console=False
            )
        text = response.choices[0].message.content
        self.assertIn("tabby-image-job:", text)
        self.assertIn(job.id, text)
        self.assertNotIn("Another picture:", text)
        self.assertNotIn("This picture:", text)

    def test_image_ready_text_is_not_doubled(self):
        data = ChatCompletionRequest(
            messages=[ChatCompletionMessage(role="user", content="a red cube")]
        )
        with mock.patch(
            "common.phrase_switch.image_job_wait_text",
            return_value="About 3 minutes to render (Flux).",
        ):
            text = image_ready_response(
                data, "generated-x.png", api_base="http://x"
            ).choices[0].message.content
        self.assertNotIn("Another picture:", text)
        self.assertNotIn("This picture:", text)
        self.assertEqual(text.count("About 3 minutes"), 1)

    def test_job_progress_line(self):
        job = SimpleNamespace(
            phase="starting_comfy", status="running", count=1, current_index=0
        )
        self.assertEqual(images_chat.job_progress_line(job), "Starting Comfy")
        job.phase = "generating"
        self.assertEqual(images_chat.job_progress_line(job), "Rendering in Comfy")
        job.phase = "restoring_llm"
        self.assertEqual(images_chat.job_progress_line(job), "Reloading the coding model")

    def test_console_inflight_hold_is_not_mixed(self):
        async def go():
            data = ChatCompletionRequest(
                messages=[
                    ChatCompletionMessage(role="user", content="draw a cube"),
                    ChatCompletionMessage(
                        role="assistant", content="tabby-image-job: job-ui"
                    ),
                    ChatCompletionMessage(role="user", content="still going?"),
                ]
            )
            job = SimpleNamespace(
                id="job-ui",
                status="running",
                items=[SimpleNamespace(output_path="images/logo.png")],
            )
            with (
                mock.patch.object(images_chat, "job_id_from_history", return_value="job-ui"),
                mock.patch.object(images_chat, "get_mcp_image_job", return_value=job),
                mock.patch.object(
                    images_chat, "_hold_then_reply", new=mock.AsyncMock(return_value="held")
                ) as hold,
            ):
                result = await images_chat.handle(
                    data, api_base="http://x", llm_ready=True, console=True
                )
            self.assertEqual(result, "held")
            self.assertTrue(hold.await_args.kwargs.get("console"))
            self.assertFalse(hold.await_args.kwargs.get("mixed"))

        asyncio.run(go())


class ConsoleChatRequestTests(unittest.TestCase):
    def test_missing_temperature_uses_default(self):
        payload = sanitize_chat_payload({"messages": [{"role": "user", "content": "hello?"}]})
        self.assertNotIn("temperature", payload)
        req = completion_request_from_payload(payload)
        self.assertIsNotNone(req.temperature)
        self.assertGreater(req.temperature, 0)

    def test_explicit_null_temperature_is_coerced(self):
        req = ChatCompletionRequest(
            messages=[ChatCompletionMessage(role="user", content="hello?")],
            temperature=None,
        )
        self.assertIsNotNone(req.temperature)


class SlashCommandTests(unittest.TestCase):
    def _req(self, text):
        return ChatCompletionRequest(messages=[ChatCompletionMessage(role="user", content=text)])

    def test_slash_help_list_restart(self):
        self.assertTrue(is_help_request(self._req("/help")))
        self.assertTrue(is_list_request(self._req("/list models")))
        self.assertTrue(is_restart_request(self._req("/restart")))

    def test_slash_profile_aliases(self):
        self.assertEqual(requested_profile(self._req("/comfy")), "comfy")
        self.assertEqual(requested_profile(self._req("/llm")), "llm")
        self.assertEqual(requested_profile(self._req("/switch to comfy")), "comfy")

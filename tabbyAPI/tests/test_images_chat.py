"""Mixed/coding chat holds until GPU PNGs exist, then curls real URLs."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from endpoints.OAI.types.chat_completion import (
    ChatCompletionMessage,
    ChatCompletionRequest,
)
from images.chat import handle, is_mixed_image_request, job_id_from_history
from images.paths import image_download_command, living_download_pairs
from images.plan import fallback_item, parse_plan_json, plan_from_extracted


def _user(text: str, *, stream: bool = False) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        messages=[ChatCompletionMessage(role="user", content=text)],
        stream=stream,
    )


def _job(**kwargs):
    items = kwargs.pop(
        "items",
        [
            SimpleNamespace(
                prompt="logo",
                output_path="images/logo.png",
                urls=kwargs.pop("item_urls", []),
                status="done",
            )
        ],
    )
    defaults = dict(
        id="job-1",
        status="done",
        error="",
        restore=True,
        items=items,
        urls=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class NestedGenerateHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_works_without_http_request(self):
        from common.networking import DisconnectHandler

        handler = DisconnectHandler(description="mixed dest extract")
        cancelled = []

        async def cancel():
            cancelled.append(True)

        await handler.add_cleanup_task("job", cancel, ())
        await handler.poll()
        await handler.finish("job")
        self.assertEqual(cancelled, [])

    async def test_abort_event_cancels_nested_job(self):
        from common.networking import DisconnectHandler

        abort = asyncio.Event()
        abort.set()
        handler = DisconnectHandler(description="nested", abort_event=abort)
        cancelled = []

        async def cancel():
            cancelled.append(True)

        await handler.add_cleanup_task("job", cancel, ())
        with self.assertRaises(asyncio.CancelledError):
            await handler.poll()
        self.assertEqual(cancelled, [True])

    def test_generate_passes_handler_not_abort_event(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath(
            "backends/exllamav3/model.py"
        ).read_text()
        self.assertIn("params,\n            handler,\n            mm_embeddings", src)
        self.assertNotIn(
            "params,\n            abort_event,\n            mm_embeddings", src
        )

    async def test_llm_plan_forwards_disconnect_handler(self):
        from images.plan import llm_plan_images

        captured = {}

        async def fake_generate(*args, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "text": '{"images":[{"filename":"logo.png","subject":"logo Cafe"}]}'
            }

        async def fake_template(_request):
            return "prompt", None

        handler = object()
        container = SimpleNamespace(
            loaded=True,
            prompt_template=object(),
            generate=fake_generate,
        )
        with mock.patch("common.model.container", container), mock.patch(
            "endpoints.OAI.utils.chat_completion.apply_chat_template",
            new=fake_template,
        ):
            items = await llm_plan_images(
                "create a website with a logo", disconnect_handler=handler
            )
        self.assertIs(captured["kwargs"].get("disconnect_handler"), handler)
        self.assertEqual(items[0]["output_path"], "images/logo.png")


class PlanTests(unittest.TestCase):
    def test_json_plan_not_regex_planets(self):
        blob = (
            '{"images":[{"filename":"logo.png","subject":"logo that says Cosmos"},'
            '{"filename":"mars.png","subject":"photograph of Mars"}]}'
        )
        rows = parse_plan_json(blob)
        items = plan_from_extracted("build a cosmos tours website with images", rows)
        dests = [row["output_path"] for row in items]
        self.assertEqual(dests, ["images/logo.png", "images/mars.png"])
        self.assertTrue(items[0]["prompt"].lower().startswith("qwen-image:"))
        self.assertNotIn("qwen-image:", items[1]["prompt"].lower())

    def test_empty_plan_falls_back_to_one_png(self):
        items = fallback_item("create a website under tours")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["output_path"].endswith("generated.png"))

    def test_pillow_wording_is_still_a_mixed_ask(self):
        data = _user(
            "Create a website with a logo and planet photos. "
            "Generate the PNGs with Python Pillow."
        )
        self.assertTrue(is_mixed_image_request(data))

    def test_menu_section_images_without_saying_website_is_mixed(self):
        data = _user(
            "create images each of the menu sections and use them on the menu. "
            "Dont add words/text to the images. Dont use svg's"
        )
        self.assertTrue(is_mixed_image_request(data))

    def test_plural_images_and_qwen_images_followup_uses_coding_history(self):
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content="Create a pizza website with HTML and CSS.",
                ),
                ChatCompletionMessage(
                    role="user",
                    content="the images created look like svg's. recreate them with qwen-images",
                ),
            ]
        )
        self.assertTrue(is_mixed_image_request(data))

    def test_create_images_using_flux_in_coding_chat_is_mixed(self):
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content="Build the homepage in html.",
                ),
                ChatCompletionMessage(
                    role="user",
                    content="create the images using flux",
                ),
            ]
        )
        self.assertTrue(is_mixed_image_request(data))

    def test_generate_an_image_of_a_menu_is_not_mixed(self):
        data = _user("generate an image of a restaurant menu")
        self.assertFalse(is_mixed_image_request(data))


class CurlFromLivingFilesTests(unittest.TestCase):
    def test_curl_lists_only_files_that_exist(self):
        job = _job(
            items=[
                SimpleNamespace(
                    prompt="logo",
                    output_path="images/logo.png",
                    urls=["https://gpu.example/v1/images/generated-logo.png"],
                    status="done",
                ),
                SimpleNamespace(
                    prompt="mars",
                    output_path="images/mars.png",
                    urls=["https://gpu.example/v1/images/generated-mars.png"],
                    status="done",
                ),
            ]
        )

        def missing(url: str) -> bool:
            return "mars" in url

        with mock.patch("images.paths.gpu_generated_file_missing", side_effect=missing):
            pairs = living_download_pairs(job)
        self.assertEqual(
            pairs,
            [("https://gpu.example/v1/images/generated-logo.png", "images/logo.png")],
        )
        command = image_download_command(pairs)
        self.assertIn("generated-logo.png", command)
        self.assertNotIn("generated-mars.png", command)
        self.assertNotIn("sleep ", command)
        self.assertNotIn("ls -l", command)

    def test_running_job_has_no_urls_to_curl(self):
        job = _job(status="running", items=[
            SimpleNamespace(
                prompt="logo",
                output_path="images/logo.png",
                urls=[],
                status="running",
            )
        ])
        with mock.patch("images.paths.gpu_generated_file_missing", return_value=False):
            self.assertEqual(living_download_pairs(job), [])


class ChatHoldTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_ask_plans_dests_via_mocked_json_not_regex(self):
        planned = [
            {"prompt": "qwen-image: logo that says Cosmos", "output_path": "images/logo.png"},
            {"prompt": "photograph of Mars", "output_path": "images/mars.png"},
        ]
        job = _job(status="queued")
        done = _job(
            status="done",
            items=[
                SimpleNamespace(
                    prompt="logo",
                    output_path="images/logo.png",
                    urls=["https://gpu.example/v1/images/generated-logo.png"],
                    status="done",
                ),
                SimpleNamespace(
                    prompt="mars",
                    output_path="images/mars.png",
                    urls=["https://gpu.example/v1/images/generated-mars.png"],
                    status="done",
                ),
            ],
        )

        async def finish(j):
            j.status = "done"
            j.items = done.items
            j.urls = [
                "https://gpu.example/v1/images/generated-logo.png",
                "https://gpu.example/v1/images/generated-mars.png",
            ]
            return j

        data = _user(
            "Create a website for Cosmos Tours with a logo and a photo of Mars."
        )
        with (
            mock.patch("images.chat.plan_mixed_dests", new=mock.AsyncMock(return_value=planned)),
            mock.patch("images.chat.active_mcp_image_job", return_value=None),
            mock.patch(
                "images.chat.start_mcp_image_job",
                new=mock.AsyncMock(return_value=(job, "started")),
            ) as start,
            mock.patch("images.chat.wait_until_done", side_effect=finish),
            mock.patch("images.paths.gpu_generated_file_missing", return_value=False),
        ):
            response = await handle(data, "https://gpu.example/v1")
        kwargs = start.await_args.kwargs
        dests = [row["output_path"] for row in kwargs["items"]]
        self.assertEqual(dests, ["images/logo.png", "images/mars.png"])
        self.assertTrue(kwargs["restore"])
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("generated-logo.png", args)
        self.assertIn("generated-mars.png", args)
        self.assertIn("tabby-image-job:", response.choices[0].message.content)
        self.assertNotIn("sleep ", args)

    async def test_fresh_chat_does_not_curl_a_leftover_job(self):
        leftover = _job(
            id="old-job",
            status="done",
            items=[
                SimpleNamespace(
                    prompt="logo",
                    output_path="images/logo.png",
                    urls=["https://gpu.example/v1/images/generated-old.png"],
                    status="done",
                )
            ],
        )
        data = _user("Create a website with a logo and header image")
        new_job = _job(id="new-job", status="queued")

        async def finish(j):
            j.status = "done"
            j.items = [
                SimpleNamespace(
                    prompt="logo",
                    output_path="images/logo.png",
                    urls=["https://gpu.example/v1/images/generated-new.png"],
                    status="done",
                )
            ]
            return j

        with (
            mock.patch(
                "images.chat.plan_mixed_dests",
                new=mock.AsyncMock(
                    return_value=[
                        {"prompt": "logo", "output_path": "images/logo.png"},
                    ]
                ),
            ),
            mock.patch("images.chat.active_mcp_image_job", return_value=None),
            mock.patch("images.chat.get_mcp_image_job", return_value=leftover),
            mock.patch(
                "images.chat.start_mcp_image_job",
                new=mock.AsyncMock(return_value=(new_job, "started")),
            ) as start,
            mock.patch("images.chat.wait_until_done", side_effect=finish),
            mock.patch("images.paths.gpu_generated_file_missing", return_value=False),
        ):
            response = await handle(data, "https://gpu.example/v1")
        start.assert_awaited()
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("generated-new.png", args)
        self.assertNotIn("generated-old.png", args)

    async def test_resume_hold_when_history_has_job_id(self):
        job = _job(id="abc-123", status="running", items=[
            SimpleNamespace(
                prompt="logo",
                output_path="images/logo.png",
                urls=[],
                status="running",
            )
        ])
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content="Create a website with a logo",
                ),
                ChatCompletionMessage(
                    role="assistant",
                    content="tabby-image-job: abc-123",
                ),
            ]
        )
        self.assertEqual(job_id_from_history(data), "abc-123")

        async def finish(j):
            j.status = "done"
            j.items[0].urls = ["https://gpu.example/v1/images/generated-logo.png"]
            j.items[0].status = "done"
            return j

        with (
            mock.patch("images.chat.get_mcp_image_job", return_value=job),
            mock.patch("images.chat.start_mcp_image_job", new=mock.AsyncMock()) as start,
            mock.patch("images.chat.wait_until_done", side_effect=finish),
            mock.patch("images.paths.gpu_generated_file_missing", return_value=False),
        ):
            response = await handle(data, "https://gpu.example/v1")
        start.assert_not_called()
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("generated-logo.png", args)

    async def test_menu_section_ask_starts_mixed_job_not_pillow(self):
        planned = [
            {"prompt": "pizza", "output_path": "images/classic-pizzas.png"},
            {"prompt": "sides", "output_path": "images/sides-appetizers.png"},
            {"prompt": "dessert", "output_path": "images/desserts.png"},
        ]
        job = _job(status="queued")

        async def finish(j):
            j.status = "done"
            j.items = [
                SimpleNamespace(
                    prompt=row["prompt"],
                    output_path=row["output_path"],
                    urls=[f"https://gpu.example/v1/images/generated-{i}.png"],
                    status="done",
                )
                for i, row in enumerate(planned)
            ]
            return j

        data = _user(
            "create images each of the menu sections and use them on the menu. "
            "Dont add words/text to the images. Dont use svg's"
        )
        with (
            mock.patch(
                "images.chat.plan_mixed_dests",
                new=mock.AsyncMock(return_value=planned),
            ),
            mock.patch("images.chat.active_mcp_image_job", return_value=None),
            mock.patch(
                "images.chat.start_mcp_image_job",
                new=mock.AsyncMock(return_value=(job, "started")),
            ) as start,
            mock.patch("images.chat.wait_until_done", side_effect=finish),
            mock.patch("images.paths.gpu_generated_file_missing", return_value=False),
        ):
            response = await handle(data, "https://gpu.example/v1")
        start.assert_awaited()
        dests = [row["output_path"] for row in start.await_args.kwargs["items"]]
        self.assertEqual(
            dests,
            [
                "images/classic-pizzas.png",
                "images/sides-appetizers.png",
                "images/desserts.png",
            ],
        )
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("generated-0.png", args)
        self.assertNotIn("Pillow", args)

    async def test_layout_followup_after_curl_does_not_start_a_job(self):
        job = _job(id="abc-123", status="done")
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content="Create a website with a logo",
                ),
                ChatCompletionMessage(
                    role="assistant",
                    content="tabby-image-job: abc-123",
                    tool_calls=[],
                ),
                ChatCompletionMessage(
                    role="user",
                    content="Make the header 80px and fix the CSS grid.",
                ),
            ]
        )
        with (
            mock.patch("images.chat.get_mcp_image_job", return_value=job),
            mock.patch("images.chat.start_mcp_image_job", new=mock.AsyncMock()) as start,
        ):
            response = await handle(data, "https://gpu.example/v1")
        self.assertIsNone(response)
        start.assert_not_called()

    async def test_busy_other_job_does_not_hijack_a_fresh_chat(self):
        busy = _job(id="other", status="running")
        data = _user("Create a website with a logo and photos")
        with (
            mock.patch("images.chat.get_mcp_image_job", return_value=None),
            mock.patch("images.chat.active_mcp_image_job", return_value=busy),
            mock.patch("images.chat.start_mcp_image_job", new=mock.AsyncMock()) as start,
        ):
            response = await handle(data, "https://gpu.example/v1")
        start.assert_not_called()
        self.assertIn("already generating", response.choices[0].message.content)

    async def test_mixed_ask_while_llm_loading_does_not_start_comfy(self):
        data = _user("Create a website with a logo and photos")
        wait = mock.AsyncMock(return_value="wait")
        with (
            mock.patch("images.chat.active_mcp_image_job", return_value=None),
            mock.patch("images.chat.start_mcp_image_job", new=mock.AsyncMock()) as start,
            mock.patch("common.phrase_switch.llm_not_ready_response", wait),
        ):
            response = await handle(
                data, "https://gpu.example/v1", llm_ready=False, gpu_is_comfy=True
            )
        start.assert_not_called()
        wait.assert_awaited()
        self.assertEqual(response, "wait")


class McpWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_tool_waits_until_job_is_done(self):
        from common.mcp_images import run_generate_tool

        job = _job(id="mcp-1", status="queued")

        async def finish(j):
            j.status = "done"
            j.items[0].urls = ["https://gpu.example/v1/images/generated-logo.png"]
            return j

        with (
            mock.patch(
                "images.jobs.start_mcp_image_job",
                new=mock.AsyncMock(return_value=(job, "started")),
            ),
            mock.patch("images.jobs.wait_until_done", side_effect=finish),
            mock.patch("images.jobs.get_mcp_image_job", return_value=None),
            mock.patch("images.jobs.loaded_tabby_name", return_value="qwen"),
            mock.patch(
                "common.gpu_mode.public_api_base", return_value="https://gpu.example/v1"
            ),
            mock.patch(
                "common.mcp_images.format_mcp_job_text",
                return_value="Job mcp-1: done\nhttps://gpu.example/v1/images/generated-logo.png",
            ),
        ):
            result = await run_generate_tool(
                {"prompt": "qwen-image: logo", "output_path": "images/logo.png"}
            )
        self.assertIn("generated-logo.png", result["content"][0]["text"])
        self.assertFalse(result["isError"])


if __name__ == "__main__":
    unittest.main()

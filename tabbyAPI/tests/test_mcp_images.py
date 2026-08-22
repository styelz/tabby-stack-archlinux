import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.mcp_images import (
    GET_JOB_NAME,
    TOOL_NAME,
    dispatch,
    initialize_result,
    list_tools_result,
    normalize_prompt,
    parse_image_items,
)


class McpImagesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from endpoints.core.image_jobs import reset_mcp_image_jobs_for_tests

        self._tmpdir = tempfile.TemporaryDirectory()
        self._gallery_patch = mock.patch(
            "common.gpu_mode.GENERATED_DIR", Path(self._tmpdir.name)
        )
        self._gallery_patch.start()
        await reset_mcp_image_jobs_for_tests()

    async def asyncTearDown(self):
        from endpoints.core.image_jobs import reset_mcp_image_jobs_for_tests

        await reset_mcp_image_jobs_for_tests()
        self._gallery_patch.stop()
        self._tmpdir.cleanup()

    def test_tools_list_exposes_generate_image(self):
        names = [tool["name"] for tool in list_tools_result()["tools"]]
        self.assertEqual(names, [TOOL_NAME, GET_JOB_NAME])
        self.assertIn("qwen-image", initialize_result()["instructions"])
        self.assertIn("job_id", initialize_result()["instructions"])
        self.assertIn("images array", initialize_result()["instructions"])
        self.assertIn("20s", initialize_result()["instructions"])

    def test_qwen_prefix(self):
        self.assertEqual(
            normalize_prompt({"prompt": "a cafe logo", "qwen_image": True}),
            "qwen-image: a cafe logo",
        )
        self.assertEqual(
            normalize_prompt({"prompt": "qwen-image: SALE", "qwen_image": True}),
            "qwen-image: SALE",
        )

    def test_parse_image_items(self):
        items = parse_image_items(
            {
                "images": [
                    {
                        "prompt": "a cafe logo",
                        "output_path": "images/logo.png",
                        "qwen_image": True,
                    },
                    {"prompt": "a header banner", "output_path": "images/header.png"},
                ]
            }
        )
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["prompt"].lower().startswith("qwen-image:"))
        self.assertIn("cafe logo", items[0]["prompt"].lower())
        self.assertIn("isolated logo mark", items[0]["prompt"].lower())
        self.assertNotIn("website", items[0]["prompt"].lower())
        self.assertEqual(items[0]["output_path"], "images/logo.png")
        self.assertEqual(items[1]["output_path"], "images/header.png")
        abs_items = parse_image_items(
            {
                "images": [
                    {
                        "prompt": "a cafe logo",
                        "output_path": "/home/pbp/Cursor/llm-test/pbptours/images/logo.png",
                    },
                    {
                        "prompt": "photograph of planet Mercury",
                        "output_path": "/home/pbp/Cursor/llm-test/pbptours/images/mercury.png",
                    },
                ]
            }
        )
        self.assertEqual(abs_items[0]["output_path"], "pbptours/images/logo.png")
        self.assertEqual(abs_items[1]["output_path"], "pbptours/images/mercury.png")
        guessed = parse_image_items(
            {
                "images": [
                    {"prompt": "qwen-image: a cafe logo"},
                    {"prompt": "a header banner"},
                    {"prompt": "a red cube"},
                    {"prompt": "a blue cube"},
                ]
            }
        )
        self.assertEqual(guessed[0]["output_path"], "images/logo.png")
        self.assertEqual(guessed[1]["output_path"], "images/header.png")
        self.assertEqual(guessed[2]["output_path"], "images/generated.png")
        self.assertEqual(guessed[3]["output_path"], "images/generated-2.png")
        self.assertIn("no website", guessed[1]["prompt"])

    async def test_initialize_and_list(self):
        init = await dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            }
        )
        self.assertEqual(init["result"]["serverInfo"]["name"], "tabby-images")
        listed = await dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(listed["result"]["tools"][0]["name"], "generate_image")
        self.assertEqual(listed["result"]["tools"][1]["name"], "get_image_job")
        schema = listed["result"]["tools"][0]["inputSchema"]["properties"]
        self.assertIn("images", schema)
        self.assertIn("wait_s", listed["result"]["tools"][1]["inputSchema"]["properties"])

    async def test_notification_has_no_payload(self):
        self.assertIsNone(
            await dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    async def test_unknown_method(self):
        reply = await dispatch({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual(reply["error"]["code"], -32601)

    async def test_unknown_tool_is_tool_error(self):
        reply = await dispatch(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "browser_navigate", "arguments": {}},
            }
        )
        self.assertTrue(reply["result"]["isError"])

    def _patch_slow_job(self):
        png = mock.Mock()
        png.name = "generated-logo.png"
        gate = asyncio.Event()

        async def slow_render(*_args, **_kwargs):
            await gate.wait()
            return [png]

        patches = (
            mock.patch("endpoints.core.image_jobs.MCP_HANDOFF_DELAY_S", 0),
            mock.patch("endpoints.core.image_jobs._render_specs", new=slow_render),
            mock.patch(
                "endpoints.core.image_jobs.ensure_comfy", new=mock.AsyncMock()
            ),
            mock.patch(
                "endpoints.core.image_jobs.reload_last_llm", new=mock.AsyncMock()
            ),
            mock.patch("endpoints.core.image_jobs.loaded_tabby_name", return_value="qwen"),
            mock.patch(
                "common.gpu_mode.public_api_base",
                return_value="https://gpu.example/v1",
            ),
            mock.patch(
                "common.gpu_mode.public_image_url",
                return_value="https://gpu.example/v1/images/generated-logo.png",
            ),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return gate

    async def _run_generate(self, **arguments):
        gate = self._patch_slow_job()
        started = await dispatch(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "generate_image",
                    "arguments": arguments
                    or {
                        "prompt": "qwen-image: Cafe logo",
                        "output_path": "images/logo.png",
                    },
                },
            }
        )
        return started, gate

    async def _poll(self, rpc_id=6, **arguments):
        args = {"wait_s": 0, **arguments}
        return await dispatch(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "method": "tools/call",
                "params": {"name": "get_image_job", "arguments": args},
            }
        )

    async def test_generate_returns_job_id_before_gpu_finishes(self):
        started, gate = await self._run_generate(
            prompt="qwen-image: Cafe logo",
            output_path="images/logo.png",
        )
        text = started["result"]["content"][0]["text"]
        self.assertIn("Queued", text)
        self.assertIn("one Comfy session", text)
        self.assertIn("images/logo.png", text)
        self.assertIn("get_image_job", text)
        self.assertNotIn("b64_json", text)
        self.assertFalse(started["result"]["isError"])
        self.assertNotIn("https://gpu.example/v1/images/generated-logo.png", text)

        poll = await self._poll()
        poll_text = poll["result"]["content"][0]["text"]
        self.assertTrue("queued" in poll_text.lower() or "running" in poll_text.lower())
        self.assertIn("Progress:", poll_text)

        gate.set()
        from endpoints.core.image_jobs import _MCP_TASK

        self.assertIsNotNone(_MCP_TASK)
        await asyncio.wait_for(_MCP_TASK, timeout=2)

        done = await self._poll(7)
        done_text = done["result"]["content"][0]["text"]
        self.assertIn("generated-logo.png", done_text)
        self.assertIn("images/logo.png", done_text)
        self.assertIn("Do not ask the user to download", done_text)

    async def test_second_generate_appends_to_the_same_batch(self):
        started, gate = await self._run_generate(prompt="qwen-image: Cafe logo")
        first = started["result"]["content"][0]["text"]
        job_line = [line for line in first.splitlines() if line.startswith("Job ")][0]
        again = await dispatch(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "generate_image",
                    "arguments": {
                        "prompt": "a cafe interior",
                        "output_path": "images/hero.png",
                    },
                },
            }
        )
        again_text = again["result"]["content"][0]["text"]
        self.assertIn("Added to the same GPU batch", again_text)
        self.assertIn(job_line.split(":")[0], again_text)
        self.assertIn("2 image", again_text)
        gate.set()
        from endpoints.core.image_jobs import _MCP_TASK

        await asyncio.wait_for(_MCP_TASK, timeout=2)
        done = await self._poll(9)
        done_text = done["result"]["content"][0]["text"]
        self.assertIn("2 image", done_text)

    async def test_images_array_is_one_job(self):
        started, gate = await self._run_generate(
            images=[
                {"prompt": "qwen-image: Cafe logo", "output_path": "images/logo.png"},
                {"prompt": "header banner", "output_path": "images/header.png"},
                {"prompt": "latte art", "output_path": "images/latte.png"},
            ]
        )
        text = started["result"]["content"][0]["text"]
        self.assertIn("Queued 3 image", text)
        self.assertIn("images/logo.png", text)
        self.assertIn("images/header.png", text)
        self.assertIn("one Comfy session", text)
        gate.set()
        from endpoints.core.image_jobs import _MCP_TASK

        await asyncio.wait_for(_MCP_TASK, timeout=2)
        done = await self._poll()
        self.assertIn("3 image", done["result"]["content"][0]["text"])

    async def test_missing_prompt(self):
        reply = await dispatch(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "generate_image", "arguments": {}},
            }
        )
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("prompt is required", reply["result"]["content"][0]["text"])

    async def test_get_is_405(self):
        from endpoints.core.mcp import mcp_get

        response = await mcp_get()
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers.get("allow"), "POST")


if __name__ == "__main__":
    unittest.main()

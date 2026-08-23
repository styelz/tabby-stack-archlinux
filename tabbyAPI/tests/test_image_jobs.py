import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endpoints.core.image_jobs import generate_images_job, loaded_tabby_name


class ImageJobsTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_restores_llm_after_handoff(self):
        png = Path("/tmp/generated-1.png")
        with (
            mock.patch("images.jobs.loaded_tabby_name", return_value="qwen"),
            mock.patch("images.jobs.last_profile", return_value="qwen"),
            mock.patch("images.jobs.ensure_comfy", new=mock.AsyncMock()) as ensure,
            mock.patch("images.jobs.reload_last_llm", new=mock.AsyncMock()) as reload,
            mock.patch("images.jobs.generate_image", return_value=b"\x89PNG"),
            mock.patch("images.jobs.save_generated_image", return_value=png),
        ):
            saved = await generate_images_job("a red cube", restore=True)
        self.assertEqual(saved, [png])
        ensure.assert_awaited_once()
        reload.assert_awaited_once_with("qwen")

    async def test_generate_stays_on_comfy_when_not_restoring(self):
        png = Path("/tmp/generated-2.png")
        with (
            mock.patch("images.jobs.loaded_tabby_name", return_value=None),
            mock.patch("images.jobs.last_profile", return_value="qwen"),
            mock.patch("images.jobs.ensure_comfy", new=mock.AsyncMock()) as ensure,
            mock.patch("images.jobs.reload_last_llm", new=mock.AsyncMock()) as reload,
            mock.patch("images.jobs.generate_image", return_value=b"\x89PNG"),
            mock.patch("images.jobs.save_generated_image", return_value=png),
        ):
            saved = await generate_images_job("a red cube", restore=False)
        self.assertEqual(saved, [png])
        ensure.assert_awaited_once()
        reload.assert_not_awaited()

    async def test_generate_items_restore_once(self):
        png = Path("/tmp/generated-3.png")
        with (
            mock.patch("images.jobs.loaded_tabby_name", return_value="qwen"),
            mock.patch("images.jobs.last_profile", return_value="qwen"),
            mock.patch("images.jobs.ensure_comfy", new=mock.AsyncMock()) as ensure,
            mock.patch("images.jobs.reload_last_llm", new=mock.AsyncMock()) as reload,
            mock.patch("images.jobs.generate_image", return_value=b"\x89PNG"),
            mock.patch("images.jobs.save_generated_image", return_value=png),
        ):
            saved = await generate_images_job(
                items=[
                    {"prompt": "qwen-image: logo", "size": "1024x1024"},
                    {"prompt": "a cafe interior"},
                    {"prompt": "latte art"},
                ],
                restore=True,
            )
        self.assertEqual(saved, [png, png, png])
        ensure.assert_awaited_once()
        reload.assert_awaited_once_with("qwen")

    def test_loaded_name_requires_a_ready_container(self):
        with mock.patch("images.jobs.model") as model_mod:
            model_mod.container = None
            self.assertIsNone(loaded_tabby_name())

    def test_batch_wait_adds_renders_not_extra_llm_reloads(self):
        from common.phrase_switch import image_job_wait_seconds

        one = image_job_wait_seconds("a red cube", restore=True, count=1)
        three = image_job_wait_seconds(
            prompts=["a red cube", "a blue cube", "a green cube"], restore=True
        )
        self.assertGreater(three, one)
        self.assertLess(three, one * 3)

    def test_job_json_includes_paths_and_urls(self):
        from endpoints.core.image_jobs import McpImageItem, McpImageJob, mcp_job_to_dict

        job = McpImageJob(
            id="job-json",
            items=[
                McpImageItem(
                    prompt="logo",
                    output_path="images/logo.png",
                    urls=["https://gpu.example/v1/images/a.png"],
                    status="done",
                )
            ],
            restore=True,
            api_base="https://gpu.example/v1",
            wait_text="about 4 minutes",
            wait_s=240,
            status="done",
            phase="done",
            urls=["https://gpu.example/v1/images/a.png"],
        )
        payload = mcp_job_to_dict(job)
        self.assertEqual(payload["id"], "job-json")
        self.assertEqual(payload["items"][0]["output_path"], "images/logo.png")
        self.assertEqual(payload["urls"][0], "https://gpu.example/v1/images/a.png")
        self.assertFalse(payload["client_saved"])

    async def test_finished_job_survives_a_restart(self):
        from endpoints.core.image_jobs import (
            McpImageItem,
            McpImageJob,
            _persist_jobs,
            get_mcp_image_job,
            reset_mcp_image_jobs_for_tests,
        )

        with tempfile.TemporaryDirectory() as raw:
            with mock.patch("common.gpu_mode.GENERATED_DIR", Path(raw)):
                await reset_mcp_image_jobs_for_tests()
                job = McpImageJob(
                    id="job-restart-done",
                    items=[
                        McpImageItem(
                            prompt="qwen-image: logo",
                            output_path="images/logo.png",
                            urls=["https://gpu.example/v1/images/a.png"],
                            status="done",
                        )
                    ],
                    restore=True,
                    api_base="https://gpu.example/v1",
                    wait_text="about 4 minutes",
                    wait_s=240,
                    status="done",
                    phase="done",
                    urls=["https://gpu.example/v1/images/a.png"],
                    client_saved=False,
                )
                from endpoints.core.image_jobs import _MCP_JOBS, _MCP_ORDER

                _MCP_JOBS[job.id] = job
                _MCP_ORDER.append(job.id)
                _persist_jobs()

                # Simulate the process restarting: RAM state is gone, disk isn't.
                await reset_mcp_image_jobs_for_tests()
                recovered = get_mcp_image_job("job-restart-done")
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered.status, "done")
                self.assertEqual(recovered.urls, ["https://gpu.example/v1/images/a.png"])
                self.assertFalse(recovered.client_saved)
                await reset_mcp_image_jobs_for_tests()

    async def test_finished_job_keeps_client_saved_across_restart(self):
        from endpoints.core.image_jobs import (
            McpImageItem,
            McpImageJob,
            _persist_jobs,
            get_mcp_image_job,
            reset_mcp_image_jobs_for_tests,
        )

        with tempfile.TemporaryDirectory() as raw:
            with mock.patch("common.gpu_mode.GENERATED_DIR", Path(raw)):
                await reset_mcp_image_jobs_for_tests()
                job = McpImageJob(
                    id="job-restart-saved",
                    items=[
                        McpImageItem(
                            prompt="qwen-image: logo",
                            output_path="images/logo.png",
                            urls=["https://gpu.example/v1/images/a.png"],
                            status="done",
                        )
                    ],
                    restore=True,
                    api_base="https://gpu.example/v1",
                    wait_text="about 4 minutes",
                    wait_s=240,
                    status="done",
                    phase="done",
                    urls=["https://gpu.example/v1/images/a.png"],
                    client_saved=True,
                )
                from endpoints.core.image_jobs import _MCP_JOBS, _MCP_ORDER

                _MCP_JOBS[job.id] = job
                _MCP_ORDER.append(job.id)
                _persist_jobs()
                await reset_mcp_image_jobs_for_tests()
                recovered = get_mcp_image_job("job-restart-saved")
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered.status, "done")
                self.assertTrue(recovered.client_saved)
                await reset_mcp_image_jobs_for_tests()

    async def test_interrupted_job_keeps_finished_items_but_errors(self):
        from endpoints.core.image_jobs import (
            McpImageItem,
            McpImageJob,
            _persist_jobs,
            active_mcp_image_job,
            get_mcp_image_job,
            reset_mcp_image_jobs_for_tests,
        )

        with tempfile.TemporaryDirectory() as raw:
            with mock.patch("common.gpu_mode.GENERATED_DIR", Path(raw)):
                await reset_mcp_image_jobs_for_tests()
                job = McpImageJob(
                    id="job-restart-partial",
                    items=[
                        McpImageItem(
                            prompt="qwen-image: logo",
                            output_path="images/logo.png",
                            urls=["https://gpu.example/v1/images/a.png"],
                            status="done",
                        ),
                        McpImageItem(
                            prompt="a cafe interior",
                            output_path="images/hero.png",
                            status="queued",
                        ),
                    ],
                    restore=True,
                    api_base="https://gpu.example/v1",
                    wait_text="about 4 minutes",
                    wait_s=240,
                    status="running",
                    phase="generating",
                    urls=["https://gpu.example/v1/images/a.png"],
                )
                from endpoints.core.image_jobs import _MCP_JOBS, _MCP_ORDER

                _MCP_JOBS[job.id] = job
                _MCP_ORDER.append(job.id)
                _persist_jobs()

                await reset_mcp_image_jobs_for_tests()
                self.assertIsNone(active_mcp_image_job())
                recovered = get_mcp_image_job("job-restart-partial")
                self.assertEqual(recovered.status, "error")
                self.assertIn("restarted", recovered.error.lower())
                self.assertEqual(recovered.urls, ["https://gpu.example/v1/images/a.png"])
                await reset_mcp_image_jobs_for_tests()

    def test_new_items_uniquify_paths(self):
        from endpoints.core.image_jobs import _new_items

        items = _new_items(
            items=[
                {"prompt": "qwen-image: cafe logo", "output_path": "images/logo.png"},
                {"prompt": "hero banner", "output_path": "images/header.png"},
                {"prompt": "a red cube"},
                {"prompt": "a blue cube"},
            ]
        )
        self.assertEqual(items[0].output_path, "images/logo.png")
        self.assertEqual(items[1].output_path, "images/header.png")
        self.assertEqual(items[2].output_path, "images/generated.png")
        self.assertEqual(items[3].output_path, "images/generated-2.png")
        self.assertTrue(items[0].prompt.lower().startswith("qwen-image:"))
        self.assertFalse(items[1].prompt.lower().startswith("qwen-image:"))

    async def test_mixed_chat_removed_from_phrase_switch(self):
        import common.phrase_switch as ps

        self.assertFalse(hasattr(ps, "ensure_mixed_image_job"))


if __name__ == "__main__":
    unittest.main()

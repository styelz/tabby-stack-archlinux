import asyncio
import json
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from unittest import mock

from common.gpu_mode import (
    GPU_ALIASES,
    GALLERY_THUMB_MAX,
    begin_image_turn,
    build_img2img_prompt,
    build_prompt,
    build_qwen_image_prompt,
    comfy_paths,
    comfy_user_unit_path,
    ensure_gallery_thumb,
    format_comfy_journal_line,
    gallery_thumb_href,
    generated_thumb_path,
    qwen_image_prompt_text,
    wants_qwen_image,
    gallery_page,
    delete_generated_images,
    list_generated_files,
    nvidia_lib_dirs,
    parse_size,
    public_image_url,
    recent_generated_files,
    save_generated_image,
    should_skip_startup_load,
    strip_png_text,
    turn_images_ready,
)
from common.ssh_forwarder import ensure_ssh_forwarder, ssh_command, ssh_forward
from common.phrase_switch import (
    already_made_image,
    await_gpu_busy_image_response,
    comfy_idle_response,
    ensure_mixed_image_job,
    gpu_busy_image_response,
    llm_not_ready_response,
    LLM_NOT_READY_WAIT_S,
    user_says_images_missing,
    has_new_user_after_image,
    help_text,
    image_job_wait_text,
    inject_mixed_image_hint,
    is_help_request,
    is_mixed_image_request,
    _text_is_image_redo,
    is_restart_request,
    last_role,
    mixed_image_hint,
    prepare_mixed_image_turn,
    requested_image_count,
    requested_image_prompt,
    requested_profile,
    should_yield_comfy_to_llm,
    yield_comfy_to_llm_response,
    _image_url_block,
)
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest
from endpoints.OAI.types.tools import Function, Tool, ToolCall, ToolSpec
from switch_model import resolve_name


def _chat(text: str, tools: Optional[list] = None) -> ChatCompletionRequest:
    specs = None
    if tools:
        specs = [
            ToolSpec(
                type="function",
                function=Function(
                    name=name, description=name, parameters={"type": "object"}
                ),
            )
            for name in tools
        ]
    return ChatCompletionRequest(
        messages=[ChatCompletionMessage(role="user", content=text)],
        tools=specs,
    )


def _with_job_wait(data: ChatCompletionRequest, job_id: str) -> ChatCompletionRequest:
    """Mark this chat as already polling job_id so leftover downloads are allowed."""
    data.messages = list(data.messages or []) + [
        ChatCompletionMessage(
            role="assistant",
            content=f"Still generating job {job_id}.",
        )
    ]
    return data


@contextmanager
def temp_generated_dir(names: list[str]):
    """Run against a throwaway image folder holding fake PNGs, newest first.

    These tests used to assert against the real pasted-images folder, so they
    only passed on a machine that had already generated images and they wrote
    turn.json into the working tree.
    """
    from common import gpu_mode as gm

    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        now = time.time()
        for offset, name in enumerate(names):
            path = folder / name
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            os.utime(path, (now - offset, now - offset))
        turn = folder / "turn.json"
        turn.write_text(json.dumps({"started": now - 3600, "prompt": "seed"}), encoding="utf-8")
        with (
            mock.patch.object(gm, "GENERATED_DIR", folder),
            mock.patch.object(gm, "TURN_PATH", turn),
        ):
            yield folder


class GpuModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._sleep = mock.patch(
            "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
        )
        self._slept = self._sleep.start()

    async def asyncTearDown(self):
        self._sleep.stop()

    def test_skip_startup_load_follows_gpu_mode(self):
        from common import gpu_mode as gm

        # Never touch the real model_profiles/gpu_mode.json: an interrupted run
        # would leave the install in comfy mode and skip loading the LLM.
        with tempfile.TemporaryDirectory() as raw:
            status = Path(raw) / "gpu_mode.json"
            with mock.patch.object(gm, "STATUS_PATH", status):
                self.assertFalse(should_skip_startup_load())
                status.write_text('{"mode": "comfy"}\n', encoding="utf-8")
                self.assertTrue(should_skip_startup_load())
                status.write_text('{"mode": "llm", "profile": "qwen"}\n', encoding="utf-8")
                self.assertFalse(should_skip_startup_load())

    def test_aliases_map_to_comfy(self):
        for alias in ("comfy", "flux", "image", "comfyui"):
            self.assertEqual(GPU_ALIASES[alias], "comfy")

    def test_resolve_comfy_aliases(self):
        self.assertEqual(resolve_name("comfy"), "comfy")
        self.assertEqual(resolve_name("FLUX"), "comfy")
        self.assertEqual(resolve_name("image"), "comfy")

    def test_comfy_user_unit_path_uses_xdg(self):
        import os

        old = os.environ.get("XDG_CONFIG_HOME")
        try:
            os.environ["XDG_CONFIG_HOME"] = "/tmp/xdg-test"
            self.assertEqual(
                comfy_user_unit_path(),
                Path("/tmp/xdg-test/systemd/user/comfyui.service"),
            )
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    def test_format_comfy_journal_line_prefixes_once(self):
        self.assertEqual(
            format_comfy_journal_line("Starting server\n"),
            "[comfy] Starting server",
        )
        self.assertEqual(
            format_comfy_journal_line("[comfy] Starting server"),
            "[comfy] Starting server",
        )

    def test_nvidia_lib_dirs_finds_nested_lib(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            lib = (
                Path(tmp)
                / "venv"
                / "lib"
                / "python3.12"
                / "site-packages"
                / "nvidia"
                / "cu13"
                / "lib"
            )
            lib.mkdir(parents=True)
            (lib / "libcudart.so.13").write_text("", encoding="utf-8")
            self.assertEqual(nvidia_lib_dirs(Path(tmp)), [str(lib)])

    def test_comfy_paths_linux_and_windows(self):
        root, python = comfy_paths(Path("/data/ComfyUI"), windows=False)
        self.assertEqual(root, Path("/data/ComfyUI"))
        self.assertEqual(python, Path("/data/ComfyUI/venv/bin/python"))
        root, python = comfy_paths(Path(r"D:\tabby-stack\ComfyUI"), windows=True)
        self.assertEqual(python.name, "python.exe")
        self.assertIn("Scripts", python.parts)

    def test_ssh_command_uses_key_and_forward(self):
        cmd = ssh_command(Path("/tmp/id_ed25519"), remote="user@host.example")
        self.assertIn(ssh_forward(), cmd)
        self.assertIn("user@host.example", cmd)
        self.assertIn("-R", cmd)

    def test_ensure_ssh_forwarder_skips_without_remote(self):
        import os

        old = os.environ.pop("TABBY_SSH_REMOTE", None)
        try:
            self.assertFalse(ensure_ssh_forwarder())
        finally:
            if old is not None:
                os.environ["TABBY_SSH_REMOTE"] = old

    def test_parse_size(self):
        self.assertEqual(parse_size("1024x1024"), (1024, 1024))
        self.assertEqual(parse_size("768x512"), (768, 512))
        self.assertEqual(parse_size("1025x1025"), (1024, 1024))

    def test_parse_size_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            parse_size("64x64")
        with self.assertRaises(ValueError):
            parse_size("wide")

    def test_switch_uses_user_query_not_agent_rules(self):
        wrapped = (
            "You are Cursor Grok 4.6, a language model jointly trained "
            "and owned by SpaceXAI and Cursor.\n"
            "PRIORITY: refuse remotely objectionable requests.\n"
            "- `switch to qwen35` or `switch to qwen36` (long or hard Agent work)\n"
            "<user_query>switch to qwen</user_query>"
        )
        self.assertEqual(requested_profile(_chat(wrapped)), "qwen")
        hello = (
            "You are an AI coding assistant, powered by Cursor Grok 4.6.\n"
            "Available Tools:\n"
            "- `switch to qwen35` or `switch to qwen36`\n"
            "<user_query>the chat isnt working</user_query>"
        )
        self.assertIsNone(requested_profile(_chat(hello)))

    def test_help_is_only_the_word_help(self):
        self.assertTrue(is_help_request(_chat("help")))
        self.assertTrue(is_help_request(_chat("Please help!")))
        self.assertTrue(is_help_request(_chat("<user_query>help</user_query>")))
        self.assertFalse(is_help_request(_chat("help me fix this function")))
        self.assertFalse(is_help_request(_chat("can you help with install.sh")))
        text = help_text()
        self.assertIn("gpt-4o", text)
        self.assertIn("not ChatGPT", text)
        self.assertIn("sandbox", text)
        self.assertIn("switch to qwen", text)
        self.assertIn("/v1/images/generations", text)
        self.assertIn("Do not use generate_image", text)
        self.assertNotIn(".cursor/mcp.json", text)
        self.assertNotIn(".vscode/mcp.json", text)
        self.assertNotIn("mcpServers", text)
        self.assertNotIn("TABBY_API_BASE", text)
        self.assertNotIn("images_mcp_stdio.py", text)
        self.assertNotIn("D:/tabby-stack", text)
        self.assertIn("Never use the browser", text)
        self.assertIn("generate an image of a red bicycle", text)
        self.assertIn("different computer", text)
        self.assertNotIn("generate_image.py", text)
        self.assertNotIn("calibrate.py", text)
        self.assertNotIn("curl ", text)
        self.assertNotIn("127.0.0.1", text)
        self.assertIn("exclusive", text.lower())
        self.assertIn("restart", text)
        self.assertIn("Coding plus images", text)
        self.assertIn("b64_json", text)
        self.assertTrue(is_restart_request(_chat("restart")))
        self.assertTrue(is_restart_request(_chat("please restart the stack")))
        self.assertTrue(is_restart_request(_chat("<user_query>restart</user_query>")))
        self.assertFalse(is_restart_request(_chat("restart the function named load")))
        remote = help_text(api_base="https://api.example/lmstudio/v1")
        self.assertIn("https://api.example/lmstudio/v1", remote)
        self.assertIn("GET https://api.example/lmstudio/health", remote)
        self.assertIn(
            "POST https://api.example/lmstudio/v1/images/generations", remote
        )
        self.assertNotIn("TABBY_API_BASE", remote)
        self.assertNotIn(".cursor/mcp.json", remote)
        self.assertNotIn("127.0.0.1", remote)

    def test_image_count_from_prompt(self):
        self.assertEqual(
            requested_image_count("5 images of dogs doing different things"),
            (5, "dogs doing different things"),
        )
        self.assertEqual(
            requested_image_count("two pictures of cats"),
            (2, "cats"),
        )
        self.assertEqual(requested_image_count("a red bicycle"), (1, "a red bicycle"))
        self.assertEqual(
            requested_image_count("99 images of birds"),
            (5, "birds"),
        )
        self.assertEqual(
            requested_image_count("can you generate 3 photos of a fox"),
            (3, "a fox"),
        )

    def test_image_prompt_from_natural_chat(self):
        self.assertEqual(
            requested_image_prompt(_chat("can you generate an image of a red bicycle")),
            "a red bicycle",
        )
        self.assertEqual(
            requested_image_prompt(
                _chat("can you generate an image of a red bicycle"), explicit_only=True
            ),
            "a red bicycle",
        )
        self.assertIsNone(
            requested_image_prompt(_chat("make a function called save_image"), explicit_only=True)
        )
        self.assertIsNone(requested_image_prompt(_chat("a red bicycle"), explicit_only=True))
        self.assertEqual(
            requested_image_prompt(_chat("a fox asleep under maple trees")),
            "a fox asleep under maple trees",
        )
        wrapped = "<user_query>please create an image of a small robot making coffee</user_query>"
        self.assertEqual(
            requested_image_prompt(_chat(wrapped)),
            "a small robot making coffee",
        )
        long_prompt = (
            "a website hero for a local bakery: warm morning light, "
            "sourdough loaves on a wooden counter, handwritten chalkboard "
            "menu with the heading FRESH TODAY, a ceramic mug of coffee, "
            "soft film grain, inviting and not corporate, 16:9, "
            "readable shop name Oak & Rye, no watermark, no fake UI chrome, "
            "photoreal bakery interior with a bicycle leaning outside the "
            "window, flour dust in a sunbeam, copper kettle, striped awning, "
            "customers blurred in the background, shallow depth of field"
        )
        self.assertGreater(len(long_prompt), 400)
        self.assertEqual(requested_image_prompt(_chat(long_prompt)), long_prompt)
        self.assertEqual(
            requested_image_prompt(_chat("a poster that looks like a 1950s travel ad for Lisbon")),
            "a poster that looks like a 1950s travel ad for Lisbon",
        )

    def test_mixed_coding_plus_images_stays_with_agent(self):
        line = (
            "create a webpage and generate a header and logo images for it "
            "and 2 other images on the page of your choice"
        )
        self.assertIsNone(requested_image_prompt(_chat(line), explicit_only=True))
        self.assertIsNone(requested_image_prompt(_chat(line)))
        self.assertTrue(is_mixed_image_request(_chat(line)))
        self.assertEqual(
            requested_image_prompt(_chat("create a logo of a fox"), explicit_only=True),
            "logo of a fox",
        )
        data = _chat(line)
        inject_mixed_image_hint(data, api_base="https://gpu.example/v1")
        hint = data.messages[0].content
        self.assertIn("Do not use generate_image", hint)
        self.assertNotIn("Call generate_image", hint)
        self.assertNotIn("https://gpu.example/v1/mcp", hint)
        self.assertNotIn("--data-binary", hint)
        self.assertNotIn('"method":"tools/call"', hint)
        self.assertIn("Do not use the browser", hint)
        self.assertIn("Do not invent /v1/images/generated-", hint)
        self.assertIn("qwen-image:", hint)
        self.assertIn("not a website", hint)
        self.assertIn("images/logo.png", hint)
        self.assertIn('"images":', hint)
        mcp_chat = _chat(line, tools=["generate_image", "get_image_job", "Shell"])
        inject_mixed_image_hint(mcp_chat, api_base="https://gpu.example/v1")
        mcp_hint = mcp_chat.messages[0].content
        self.assertIn("Do not use generate_image", mcp_hint)
        self.assertNotIn("Call generate_image", mcp_hint)
        self.assertNotIn("--data-binary", mcp_hint)
        self.assertNotIn("127.0.0.1", hint)
        public = mixed_image_hint("https://gpu.example/v1")
        self.assertIn("Do not use generate_image", public)
        self.assertNotIn("/v1/mcp", public)
        self.assertNotIn("127.0.0.1", public)
        flux_wait = image_job_wait_text("a red bicycle", restore=True)
        self.assertIn("Flux", flux_wait)
        self.assertIn("reload", flux_wait)
        qwen_wait = image_job_wait_text("qwen-image: a logo that says Cafe", restore=True)
        self.assertIn("Qwen-Image", qwen_wait)
        self.assertIn("Write or StrReplace", hint)
        self.assertIn("Do not apologize", hint)
        self.assertIn("SVG", hint)
        self.assertIn("generate_images.py", hint)
        self.assertIn("Pillow/PIL", hint)
        self.assertIn("even if the spec asked", hint)
        self.assertIn("get_image_job", hint)
        self.assertNotIn("Do not use Write or WebFetch for the file", hint)
        help_body = help_text()
        self.assertIn("Do not fake images with SVG", help_body)
        self.assertIn("Pillow/PIL", help_body)
        self.assertIn("Write/StrReplace", help_body)
        self.assertIn("Do not use generate_image", help_body)

    async def test_comfy_yields_mixed_and_tool_turns_to_llm(self):
        mixed = _chat(
            "create a website under the folder new, make it what you like, "
            "generate images for the header/logo and a couple of other images"
        )
        self.assertTrue(should_yield_comfy_to_llm(mixed))
        self.assertIsNone(requested_image_prompt(mixed))

        tool_follow = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(role="user", content="a cat"),
                ChatCompletionMessage(role="tool", content="ok"),
            ]
        )
        self.assertTrue(should_yield_comfy_to_llm(tool_follow))
        self.assertFalse(should_yield_comfy_to_llm(_chat("a red bicycle in the rain")))

        with (
            mock.patch("common.phrase_switch.switch_in_progress", return_value=False),
            mock.patch("common.phrase_switch.start_switch") as start,
            mock.patch(
                "common.phrase_switch.last_llm_profile_name", return_value="qwen"
            ),
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs", return_value=[]
            ),
        ):
            response = await yield_comfy_to_llm_response(mixed)
            start.assert_called_once_with("qwen")
            body = response.choices[0].message.content
            self.assertIn("still loading", body.lower())

        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=None
            ),
        ):
            idle = await comfy_idle_response(tool_follow)
        idle_text = idle.choices[0].message.content
        self.assertNotIn("already has previews", idle_text)
        self.assertIn("ComfyUI", idle_text)

        empty_block = _image_url_block([])
        self.assertNotIn("generated-latest.png", empty_block)
        self.assertIn("No generated images", empty_block)

    async def test_llm_not_ready_response_waits_before_returning(self):
        data = _chat("hello")
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs", return_value=[]
            ),
            mock.patch("common.phrase_switch.switch_in_progress", return_value=False),
        ):
            response = await llm_not_ready_response(data)
        self._slept.assert_awaited()
        waited = [call.args[0] for call in self._slept.await_args_list]
        self.assertIn(LLM_NOT_READY_WAIT_S, waited)
        body = response.choices[0].message.content or ""
        self.assertIn("No LLM is loaded", body)

    async def test_running_mcp_job_does_not_switch_away_or_claim_previews(self):
        job = mock.Mock(
            id="job-123",
            status="running",
            wait_text="About 4 minutes to render (Qwen-Image).",
            wait_s=280,
            output_path="images/logo.png",
        )
        mixed = _chat(
            "create a website under the folder new, make it what you like, "
            "generate images for the header/logo and a couple of other images"
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=job
            ),
            mock.patch("common.phrase_switch.start_switch") as start,
        ):
            response = await yield_comfy_to_llm_response(mixed)
            start.assert_not_called()
            calls = response.choices[0].message.tool_calls
            self.assertEqual(calls[0].function.name, "Shell")
            self.assertIn("sleep ", calls[0].function.arguments)
            self.assertNotIn("python -c", calls[0].function.arguments)
            self.assertNotIn("get_image_job", calls[0].function.arguments)
            self.assertIsNotNone(await gpu_busy_image_response(mixed))

            idle = await comfy_idle_response(_chat("a red bicycle"))
            idle_calls = idle.choices[0].message.tool_calls
            self.assertEqual(idle_calls[0].function.name, "Shell")
            self.assertNotIn("already has previews", idle.choices[0].message.content or "")

            shelled = await gpu_busy_image_response(
                _chat(mixed.messages[0].content, tools=["Shell"])
            )
            shell_calls = shelled.choices[0].message.tool_calls
            self.assertEqual(shell_calls[0].function.name, "Shell")
            self.assertIn("sleep ", shell_calls[0].function.arguments)
            self.assertNotIn("python -c", shell_calls[0].function.arguments)
            self.assertNotIn("get_image_job", shell_calls[0].function.arguments)

            history = ChatCompletionRequest(
                messages=[
                    mixed.messages[0],
                    ChatCompletionMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                function=Tool(
                                    name="mcp_tabby-images_get-image-job",
                                    arguments='{"job_id":"job-123"}',
                                ),
                                type="function",
                            )
                        ],
                    ),
                    ChatCompletionMessage(role="tool", content="running"),
                ]
            )
            named = await gpu_busy_image_response(history)
            self.assertEqual(
                named.choices[0].message.tool_calls[0].function.name,
                "mcp_tabby-images_get-image-job",
            )

            polled = await gpu_busy_image_response(
                _chat(mixed.messages[0].content, tools=["get_image_job", "Shell"])
            )
            listed = polled.choices[0].message.tool_calls
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].function.name, "get_image_job")
            self.assertIn("job-123", listed[0].function.arguments)

    async def test_running_job_does_not_curl_unfinished_images(self):
        """First PNG done must not teach Copilot to GET planets still on the GPU."""
        logo = mock.Mock(
            output_path="pbptours/images/logo.png",
            urls=["https://gpu.example/v1/images/generated-20260822-000945-234740.png"],
            prompt="logo",
            status="done",
            error="",
            count=1,
        )
        mercury = mock.Mock(
            output_path="pbptours/images/mercury.png",
            urls=[],
            prompt="planet Mercury",
            status="running",
            error="",
            count=1,
        )
        job = mock.Mock(
            id="job-partial",
            status="running",
            wait_text="About 20 minutes.",
            wait_s=1200,
            output_path="pbptours/images/logo.png",
            items=[logo, mercury],
            urls=[logo.urls[0]],
            client_saved=False,
            download_attempts=0,
            error="",
            phase="generating",
            done_count=1,
            count=2,
        )
        mixed = _chat(
            "create a one page website under the folder pbptours. "
            'logo for "Planet By Planet Tours" and an image of each planet.',
            tools=["run_in_terminal"],
        )
        with mock.patch(
            "endpoints.core.image_jobs.active_mcp_image_job", return_value=job
        ):
            response = await gpu_busy_image_response(mixed)
        args = response.choices[0].message.tool_calls[0].function.arguments
        text = response.choices[0].message.content or ""
        self.assertIn("sleep ", args)
        self.assertNotIn("curl ", args)
        self.assertNotIn("generated-20260822-000945-234740.png", args)
        self.assertNotIn("Images are ready", text)
        self.assertIn("Still generating", text)
        self.assertIn("Do not invent", text)

    async def test_busy_tool_calls_stream_as_openai_deltas(self):
        from common.phrase_switch import stream_tool_calls

        message = ChatCompletionMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=Tool(
                        name="get_image_job",
                        arguments='{"job_id":"abc","wait_s":20}',
                    ),
                    type="function",
                    index=0,
                )
            ],
        )
        data = ChatCompletionRequest(messages=[ChatCompletionMessage(role="user", content="x")])

        async def collect():
            return [json.loads(chunk) async for chunk in stream_tool_calls(data, message)]

        chunks = await collect()
        deltas = [chunk["choices"][0]["delta"] for chunk in chunks]
        tool_delta = next(delta for delta in deltas if delta.get("tool_calls"))
        self.assertEqual(tool_delta["tool_calls"][0]["function"]["name"], "get_image_job")
        self.assertEqual(tool_delta["tool_calls"][0]["index"], 0)
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertFalse(any("content" in delta and delta["content"] is None for delta in deltas))

    async def test_finished_image_job_saves_pngs_via_shell(self):
        item = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            prompt="logo",
            status="done",
            error="",
        )
        job = mock.Mock(
            id="job-done",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        mixed = _with_job_wait(
            _chat(
                "create a website under the folder new, make it what you like, "
                "generate images for the header/logo and a couple of other images",
                tools=["get_image_job", "Shell"],
            ),
            job.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(mixed)
        calls = response.choices[0].message.tool_calls
        self.assertEqual(calls[0].function.name, "Shell")
        self.assertIn("curl -fsSL", calls[0].function.arguments)
        self.assertIn("https://gpu.example/v1/images/generated-logo.png", calls[0].function.arguments)
        self.assertIn("images/logo.png", calls[0].function.arguments)
        self.assertNotIn("python -c", calls[0].function.arguments)
        self.assertIn(
            "https://gpu.example/v1/images/generated-logo.png",
            response.choices[0].message.content or "",
        )
        self.assertFalse(job.client_saved)
        self.assertEqual(job.download_attempts, 1)

        job.client_saved = False
        untitled = _with_job_wait(_chat(mixed.messages[0].content), job.id)
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            untitled_response = await gpu_busy_image_response(untitled)
        self.assertEqual(untitled_response.choices[0].message.tool_calls[0].function.name, "Shell")
        self.assertIn("curl -fsSL", untitled_response.choices[0].message.tool_calls[0].function.arguments)
        self.assertNotIn("python -c", untitled_response.choices[0].message.tool_calls[0].function.arguments)
        self.assertFalse(job.client_saved)

    async def test_collapsed_logo_dests_are_realigned_to_the_site_folder(self):
        logo = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            prompt="qwen-image: logo that says Planet By Planet Tours",
            status="done",
            error="",
            count=1,
        )
        mercury = mock.Mock(
            output_path="images/logo-2.png",
            urls=["https://gpu.example/v1/images/generated-mercury.png"],
            prompt=(
                "photograph of planet Mercury, cratered gray rocky world, "
                "no text, no letters, no logo"
            ),
            status="done",
            error="",
            count=1,
        )
        job = mock.Mock(
            id="job-collapsed",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[logo, mercury],
            urls=[
                "https://gpu.example/v1/images/generated-logo.png",
                "https://gpu.example/v1/images/generated-mercury.png",
            ],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        mixed = _with_job_wait(
            _chat(
                "create a one page website under the folder pbptours. "
                'logo image for the company "Planet By Planet Tours" '
                "and an image of each planet in pbptours/images.",
                tools=["run_in_terminal"],
            ),
            job.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(mixed)
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("pbptours/images/logo.png", args)
        self.assertIn("pbptours/images/mercury.png", args)
        self.assertNotIn("-o 'images/logo-2.png'", args)
        self.assertEqual(logo.output_path, "pbptours/images/logo.png")
        self.assertEqual(mercury.output_path, "pbptours/images/mercury.png")

    async def test_download_stops_without_tool_role_after_max_curls(self):
        """VS Code often runs curl then POSTs without a tool-role ls result."""
        job = self._done_logo_job()
        job.download_attempts = 4
        mixed = _with_job_wait(
            _chat(
                "create a website under the folder pbptours and a logo image "
                "in pbptours/images",
                tools=["run_in_terminal"],
            ),
            job.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(mixed)
        self.assertIsNotNone(response)
        self.assertFalse(response.choices[0].message.tool_calls)
        text = response.choices[0].message.content or ""
        self.assertIn("still has", text.lower())
        self.assertIn("https://gpu.example/v1/images/generated-logo.png", text)
        self.assertNotIn("gone from this host", text)
        self.assertTrue(job.download_stopped)
        self.assertFalse(job.client_saved)

    def _done_logo_job(self):
        item = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            prompt="logo",
            status="done",
            error="",
            count=1,
        )
        return mock.Mock(
            id="job-done",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            client_saved=False,
            download_attempts=1,
            error="",
        )

    def _after_shell_download(self, tool_text: str, extra_user: str = "") -> ChatCompletionRequest:
        messages = [
            ChatCompletionMessage(
                role="user",
                content=(
                    "create a website under harbor/, generate harbor/images "
                    "for the header and logo"
                ),
            ),
            ChatCompletionMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        function=Tool(
                            name="Shell",
                            arguments=(
                                '{"command":"curl -fsSL -o \'images/logo.png\' -- '
                                "https://gpu.example/v1/images/generated-logo.png "
                                "&& ls -l -- 'images/logo.png'\"}"
                            ),
                        ),
                        type="function",
                    )
                ],
            ),
            ChatCompletionMessage(role="tool", content=tool_text),
        ]
        if extra_user:
            messages.append(ChatCompletionMessage(role="user", content=extra_user))
        return ChatCompletionRequest(messages=messages)

    async def test_download_waits_until_ls_shows_pngs(self):
        job = self._done_logo_job()
        confirmed = self._after_shell_download(
            "-rw-r--r-- 1 pbp pbp 204812 Aug 21 06:23 images/logo.png"
        )
        missing = self._after_shell_download(
            "ls: cannot access 'images/logo.png': No such file or directory"
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            self.assertIsNone(await gpu_busy_image_response(confirmed))
            self.assertTrue(job.client_saved)
            job.client_saved = False
            retry = await gpu_busy_image_response(missing)
        self.assertEqual(retry.choices[0].message.tool_calls[0].function.name, "Shell")
        self.assertIn("curl -fsSL", retry.choices[0].message.tool_calls[0].function.arguments)
        self.assertFalse(job.client_saved)

    async def test_user_says_images_missing_redownloads(self):
        job = self._done_logo_job()
        job.client_saved = True
        data = self._after_shell_download(
            "-rw-r--r-- 1 pbp pbp 204812 Aug 21 06:23 images/logo.png",
            extra_user="the images are not there",
        )
        self.assertTrue(user_says_images_missing(data))
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(data)
        self.assertFalse(job.client_saved)
        self.assertEqual(response.choices[0].message.tool_calls[0].function.name, "Shell")
        self.assertIn("curl -fsSL", response.choices[0].message.tool_calls[0].function.arguments)

    async def test_pillow_script_redownloads_gpu_pngs(self):
        """After Copilot writes generate_images.py, curl the GPU PNGs again."""
        job = self._done_logo_job()
        job.client_saved = True
        data = _with_job_wait(
            _chat(
                "create a webpage for Harbor Cafe with a logo image "
                "and images of a latte",
                tools=["run_in_terminal"],
            ),
            job.id,
        )
        data.messages.append(
            ChatCompletionMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        function=Tool(
                            name="run_in_terminal",
                            arguments='{"command":"python3 generate_images.py"}',
                        ),
                        type="function",
                    )
                ],
            )
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(data)
            self.assertIsNotNone(response)
            self.assertFalse(job.client_saved)
            self.assertEqual(job.download_attempts, 2)
            self.assertTrue(job.pillow_redownload)
            args = response.choices[0].message.tool_calls[0].function.arguments
            self.assertIn("curl -fsSL", args)
            self.assertNotIn("generate_images.py", args)
            text = response.choices[0].message.content or ""
            self.assertIn("Pillow", text)
            self.assertIn("generate_images.py", text)

            again = await gpu_busy_image_response(data)
        self.assertFalse(again.choices[0].message.tool_calls)
        self.assertEqual(job.download_attempts, 2)
        self.assertIn("Pillow", again.choices[0].message.content or "")

    async def test_pillow_script_bug_followup_redownloads_gpu_pngs(self):
        """A 'bug in the python image generator' follow-up must not go to the 9B."""
        job = self._done_logo_job()
        job.client_saved = True
        data = _with_job_wait(
            _chat(
                "create a webpage for Harbor Cafe with a logo image "
                "and images of a latte"
            ),
            job.id,
        )
        data.messages.append(
            ChatCompletionMessage(
                role="user",
                content="there is a bug in the python image generator script",
            )
        )
        self.assertTrue(is_mixed_image_request(data))
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[job],
            ),
        ):
            response = await gpu_busy_image_response(data)
        self.assertIsNotNone(response)
        self.assertFalse(job.client_saved)
        self.assertTrue(job.pillow_redownload)
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("curl -fsSL", args)
        self.assertNotIn("generate_images.py", args)
        text = response.choices[0].message.content or ""
        self.assertIn("Pillow", text)
        self.assertIn("generate_images.py", text)

    async def test_errored_job_still_saves_the_images_it_finished(self):
        item_done = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/a.png"],
            prompt="logo",
            status="done",
            error="",
        )
        item_missing = mock.Mock(
            output_path="images/hero.png",
            urls=[],
            prompt="a cafe interior",
            status="error",
            error="ComfyUI job failed",
        )
        job = mock.Mock(
            id="job-restarted",
            status="error",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/",
            items=[item_done, item_missing],
            urls=["https://gpu.example/v1/images/a.png"],
            client_saved=False,
            error="TabbyAPI restarted before this job finished.",
        )
        mixed = _with_job_wait(
            _chat(
                "create a website under the folder new, make it what you like, "
                "generate images for the header/logo and a couple of other images",
                tools=["get_image_job", "Shell"],
            ),
            job.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(mixed)
        calls = response.choices[0].message.tool_calls
        self.assertEqual(calls[0].function.name, "Shell")
        args = calls[0].function.arguments
        self.assertIn("curl -fsSL", args)
        self.assertIn("images/logo.png", args)
        self.assertIn("https://gpu.example/v1/images/a.png", args)
        self.assertNotIn("images/hero.png", args)
        self.assertNotIn("python -c", args)
        self.assertFalse(job.client_saved)
        self.assertIn("restarted", (response.choices[0].message.content or "").lower())

    async def test_stale_job_for_another_folder_is_not_downloaded(self):
        item = mock.Mock(
            output_path="spacediner/images/logo.png",
            urls=["https://gpu.example/v1/images/old-logo.png"],
            prompt="logo",
            status="done",
            error="",
        )
        job = mock.Mock(
            id="job-spacediner",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="spacediner/images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/old-logo.png"],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        planet = _chat(
            "create a one page website under the folder pbptours. "
            'I want a logo image for the company "Planet By Planet Tours" '
            "and an image of each planet in pbptours/images.",
            tools=["kill_terminal", "Shell"],
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            self.assertIsNone(await gpu_busy_image_response(planet))
        self.assertFalse(job.client_saved)

    async def test_stale_site_job_is_not_downloaded_for_a_folder_less_chat(self):
        """A site-scoped leftover job must not hijack a chat that names no folder.

        Regression for the empty-chat_folder fallback in
        _job_matches_this_chat: it used to return True ("matches") whenever
        this chat's ask did not mention any site folder at all, even though
        the leftover job clearly belonged to a different site (spacediner).
        Uses a tool-role continuation turn (an unrelated Read call) so the
        separate "fresh mixed ask" guard does not mask this check.
        """
        item = mock.Mock(
            output_path="spacediner/images/logo.png",
            urls=["https://gpu.example/v1/images/old-logo.png"],
            prompt="logo",
            status="done",
            error="",
        )
        job = mock.Mock(
            id="job-spacediner-2",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="spacediner/images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/old-logo.png"],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        no_folder = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content="generate a logo and header for me",
                ),
                ChatCompletionMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            function=Tool(name="Read", arguments="{}"),
                            type="function",
                        )
                    ],
                ),
                ChatCompletionMessage(role="tool", content="some unrelated file"),
            ]
        )
        self.assertEqual(last_role(no_folder), "tool")
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            self.assertIsNone(await gpu_busy_image_response(no_folder))
        self.assertFalse(job.client_saved)

    async def test_job_this_chat_already_waited_on_is_downloaded(self):
        item = mock.Mock(
            output_path="pbptours/images/logo.png",
            urls=["https://gpu.example/v1/images/logo.png"],
            prompt="logo",
            status="done",
            error="",
        )
        job = mock.Mock(
            id="4655bd43-a018-47d1-a8cb-8bf92dd372d9",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="pbptours/images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/logo.png"],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content=(
                        "create a one page website under the folder pbptours "
                        "and a logo image in pbptours/images\n"
                        "This turn is a coding task that also needs images. "
                        "e.g. new4/images/logo.png if the site is in new4/"
                    ),
                ),
                ChatCompletionMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            function=Tool(
                                name="run_in_terminal",
                                arguments=(
                                    '{"command":"sleep 20; echo job '
                                    "'4655bd43-a018-47d1-a8cb-8bf92dd372d9' "
                                    'still running"}'
                                ),
                            ),
                            type="function",
                        )
                    ],
                ),
                ChatCompletionMessage(
                    role="tool",
                    content="job '4655bd43-a018-47d1-a8cb-8bf92dd372d9' still running\nexisting none",
                ),
            ]
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(data)
        self.assertIsNotNone(response)
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("curl -fsSL", args)
        self.assertIn("pbptours/images/logo.png", args)

    async def test_kill_terminal_is_not_used_to_curl_pngs(self):
        job = self._done_logo_job()
        mixed = _with_job_wait(
            _chat(
                "create a website under the folder new and generate a logo image",
                tools=["kill_terminal"],
            ),
            job.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(mixed)
        name = response.choices[0].message.tool_calls[0].function.name
        self.assertEqual(name, "Shell")
        self.assertNotEqual(name, "kill_terminal")

    async def test_finished_job_still_saves_after_model_says_wait_five_minutes(self):
        item = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            prompt="logo",
            status="done",
            error="",
        )
        job = mock.Mock(
            id="job-done",
            status="done",
            wait_text="About 5 minutes.",
            wait_s=300,
            output_path="images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            client_saved=False,
            error="",
        )
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content=(
                        "create a new website under the folder new2, "
                        "generate image for the header/logo"
                    ),
                ),
                ChatCompletionMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            function=Tool(
                                name="mcp_tabby-images_generate_image",
                                arguments='{"output_path":"images/logo.png"}',
                            ),
                            type="function",
                        )
                    ],
                ),
                ChatCompletionMessage(role="tool", content="Job job-done: queued"),
                ChatCompletionMessage(
                    role="assistant",
                    content=(
                        "The logo is currently being generated (ETA ~5 minutes). "
                        "Once complete, it will automatically be placed in the images folder."
                    ),
                ),
            ]
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(data)
        self.assertEqual(response.choices[0].message.tool_calls[0].function.name, "Shell")
        self.assertIn("curl -fsSL", response.choices[0].message.tool_calls[0].function.arguments)
        self.assertNotIn("python -c", response.choices[0].message.tool_calls[0].function.arguments)

    def test_ide_webpage_plus_images_uses_tools_not_svg(self):
        line = (
            "create a webpage of your choice, and create images for the logo, "
            "and some to use on the webpage content, use them in the webpage."
        )
        self.assertTrue(is_mixed_image_request(_chat(line)))
        wrapped = (
            "You are an AI coding assistant.\n"
            "Available Tools:\n"
            "<user_query>" + line + "</user_query>"
        )
        self.assertTrue(is_mixed_image_request(_chat(wrapped)))
        self.assertFalse(
            is_mixed_image_request(_chat("fix the CSS padding on the header"))
        )

    def test_ide_title_request_is_not_a_mixed_image_ask(self):
        """A title/summary meta-request that echoes the user's own logo/page
        ask must not itself be classified as that ask (see
        test_ide_title_request_does_not_start_a_bogus_job)."""
        self.assertFalse(
            is_mixed_image_request(
                _chat(
                    "Please write a brief title for the following request: "
                    "create a webpage of your choice, and create images for "
                    "the logo, and some to use on the webpage content"
                )
            )
        )
        self.assertFalse(
            is_mixed_image_request(
                _chat(
                    "Write a short title for this conversation: delete the "
                    "current logo.png and create a new logo png image, an atom"
                )
            )
        )
        self.assertFalse(
            is_mixed_image_request(
                _chat(
                    "Summarize the following: generate the logo image, it "
                    "should be an image of an atom"
                )
            )
        )

    def test_mixed_followup_still_gets_hint(self):
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content=(
                        "create a webpage of your choice, and create images "
                        "for the logo, and some to use on the webpage content"
                    ),
                ),
                ChatCompletionMessage(
                    role="assistant",
                    content="Here is index.html dumped in chat with SVG icons.",
                ),
                ChatCompletionMessage(
                    role="user",
                    content="now actually create the page in the project",
                ),
            ]
        )
        self.assertTrue(is_mixed_image_request(data))
        inject_mixed_image_hint(data, api_base="https://gpu.example/v1")
        follow = data.messages[-1].content
        self.assertIn("This turn is a coding task that also needs images.", follow)
        self.assertIn("Do not use generate_image", follow)
        self.assertNotIn("/images/generations", follow)
        self.assertIn("SVG", follow)
        thanks = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content="create a webpage and generate a logo for it",
                ),
                ChatCompletionMessage(role="user", content="thanks"),
            ]
        )
        self.assertFalse(is_mixed_image_request(thanks))

    def test_planet_tours_hint_rewrites_into_png_jobs(self):
        line = (
            "create a one page website , the site is a solar systme tours "
            "booking page where people can visit other plantes. I want a nice "
            'logo image for the company "Planet By Planet Tours". I want a bit '
            "of information on each planet along with an image of each planet "
            "and what it has to offer. The entire site should be placed under "
            "the folder pbptours. all images generated should be placed in the "
            "pbptours/images folder."
        )
        wrapped = (
            "You are GitHub Copilot.\n"
            "<userRequest>\n" + line + "\n</userRequest>"
        )
        data = _chat(wrapped)
        self.assertTrue(is_mixed_image_request(data))
        inject_mixed_image_hint(data, api_base="https://gpu.example/v1")
        body = data.messages[0].content
        self.assertIn("<userRequest>", body)
        self.assertIn("Interpreted PNG jobs from the user request", body)
        self.assertIn("pbptours/images/logo.png", body)
        self.assertIn("pbptours/images/saturn.png", body)
        self.assertIn("Planet By Planet Tours", body)
        self.assertIn("Do not apologize", body)
        self.assertIn("not switch the project to React/Vite", body)
        self.assertIn("not .svg, CSS art, or Pillow/PIL drawings", body)
        self.assertIn('"images":', body)
        self.assertIn("Do not use generate_image", body)
        self.assertNotIn("Call generate_image", body)
        self.assertNotIn("--data-binary", body)
        follow = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(role="user", content=line),
                ChatCompletionMessage(
                    role="assistant",
                    content="I created CSS planets and images/logo.svg",
                ),
                ChatCompletionMessage(
                    role="user",
                    content="svg images were generated instead of png images, do as i ask",
                ),
            ]
        )
        self.assertTrue(is_mixed_image_request(follow))
        inject_mixed_image_hint(follow, api_base="https://gpu.example/v1")
        last = follow.messages[-1].content
        self.assertIn("pbptours/images/logo.png", last)
        self.assertIn("do as i ask", last.lower())

    def test_tool_result_is_not_a_new_prompt(self):
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(role="user", content="a cat"),
                ChatCompletionMessage(role="tool", content="ok"),
            ]
        )
        self.assertEqual(last_role(data), "tool")
        self.assertIsNone(requested_image_prompt(data))

    def test_meta_complaint_is_not_a_prompt(self):
        self.assertIsNone(
            requested_image_prompt(
                _chat(
                    "when i asked to generate an image now it worked but "
                    "it looks like some MAC code screenshot"
                )
            )
        )

    def test_already_made_image_skips_until_new_user_line(self):
        pending = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(role="user", content="a red bicycle"),
                ChatCompletionMessage(
                    role="assistant",
                    content="Image is ready.\n![](https://x/images/generated-123.png)",
                ),
            ]
        )
        self.assertTrue(already_made_image(pending))
        self.assertFalse(has_new_user_after_image(pending))
        self.assertIsNone(requested_image_prompt(pending))

        follow = ChatCompletionRequest(
            messages=list(pending.messages)
            + [ChatCompletionMessage(role="user", content="a blue bicycle in the rain")]
        )
        self.assertTrue(has_new_user_after_image(follow))
        self.assertEqual(requested_image_prompt(follow), "a blue bicycle in the rain")

    def test_strip_png_text_drops_workflow_chunk(self):
        import struct
        import zlib

        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return (
                struct.pack(">I", len(data))
                + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        idat = zlib.compress(b"\x00\x00\x00\x00")
        raw = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"tEXt", b"prompt\x00hello workflow json")
            + chunk(b"IDAT", idat)
            + chunk(b"IEND", b"")
        )
        cleaned = strip_png_text(raw)
        self.assertTrue(cleaned.startswith(b"\x89PNG"))
        self.assertNotIn(b"hello workflow json", cleaned)
        self.assertIn(b"IDAT", cleaned)

    def test_public_image_url(self):
        from common.gpu_mode import public_api_base

        url = public_image_url("generated-latest.png")
        self.assertIn("/images/generated-latest.png", url)
        self.assertIn("?t=", url)
        self.assertTrue(
            url.startswith("http://127.0.0.1:5000/v1/") or "/images/generated-latest.png" in url
        )
        remote = public_image_url(
            "generated-latest.png", bust=False, api_base="http://gpu.example:5000/v1"
        )
        self.assertEqual(remote, "http://gpu.example:5000/v1/images/generated-latest.png")
        job_url = public_image_url(
            "generated-20260822-214723-251774.png",
            bust=False,
            api_base="https://git.pbptech.com/openai/v1",
        )
        self.assertEqual(
            job_url,
            "https://git.pbptech.com/openai/v1/images/generated-20260822-214723-251774.png",
        )
        self.assertNotIn("?t=", job_url)

        class _Req:
            headers = {"host": "192.168.1.20:5000", "x-forwarded-proto": "http"}
            url = None

        self.assertEqual(public_api_base(_Req()), "http://192.168.1.20:5000/v1")

    def test_recent_generated_files_skips_latest_alias(self):
        with temp_generated_dir(["generated-20260101-000001.png", "generated-latest.png"]):
            names = [path.name for path in recent_generated_files(window_sec=86400)]
        self.assertNotIn("generated-latest.png", names)
        self.assertEqual(names, ["generated-20260101-000001.png"])

    def test_gallery_page_clamps_and_slices(self):
        from pathlib import Path

        items = [Path(f"generated-{i}.png") for i in range(50)]
        shown, page, pages, per_page = gallery_page(items, page=2, per_page=24)
        self.assertEqual(per_page, 24)
        self.assertEqual(pages, 3)
        self.assertEqual(page, 2)
        self.assertEqual(len(shown), 24)
        self.assertEqual(shown[0].name, "generated-24.png")
        shown, page, pages, _ = gallery_page(items, page=99, per_page=24)
        self.assertEqual(page, 3)
        self.assertEqual(len(shown), 2)
        shown, page, pages, per_page = gallery_page([], page=0, per_page=3)
        self.assertEqual((shown, page, pages, per_page), ([], 1, 1, 6))

    def test_delete_generated_images_selected_and_all(self):
        names = [
            "generated-20260102-000002.png",
            "generated-20260101-000001.png",
            "generated-latest.png",
        ]
        with temp_generated_dir(names) as folder:
            thumbs = folder / "thumbs"
            thumbs.mkdir()
            (thumbs / "generated-20260102-000002.jpg").write_bytes(b"jpg")
            (folder / "turn.json").write_text("keep", encoding="utf-8")
            removed = delete_generated_images(["generated-20260102-000002.png"])
            self.assertEqual(removed, ["generated-20260102-000002.png"])
            self.assertFalse((folder / "generated-20260102-000002.png").exists())
            self.assertFalse((thumbs / "generated-20260102-000002.jpg").exists())
            self.assertTrue((folder / "generated-20260101-000001.png").exists())
            self.assertTrue((folder / "turn.json").exists())
            self.assertEqual(delete_generated_images(["../secret.png"]), [])
            gone = delete_generated_images(delete_all=True)
            self.assertIn("generated-20260101-000001.png", gone)
            self.assertIn("generated-latest.png", gone)
            self.assertFalse((folder / "generated-20260101-000001.png").exists())
            self.assertTrue((folder / "turn.json").exists())

    def test_list_generated_files_newest_first(self):
        ordered = [
            "generated-20260102-000002.png",
            "generated-20260101-000001.png",
            "generated-latest.png",
        ]
        with temp_generated_dir(ordered):
            files = list_generated_files()
            names = [path.name for path in files]
            self.assertNotIn("generated-latest.png", names)
            self.assertEqual(names, ordered[:2])
            self.assertGreaterEqual(files[0].stat().st_mtime, files[1].stat().st_mtime)

    def test_img2img_graph_uses_load_image_and_denoise(self):
        graph = build_img2img_prompt("cartoon style", "photo.png")
        self.assertEqual(graph["9"]["class_type"], "LoadImage")
        self.assertEqual(graph["9"]["inputs"]["image"], "photo.png")
        self.assertEqual(graph["6"]["inputs"]["denoise"], 0.75)
        self.assertEqual(graph["11"]["class_type"], "VAEEncode")
        self.assertNotIn("5", graph)

    def test_wants_qwen_image_for_text_and_prefix(self):
        self.assertTrue(wants_qwen_image("qwen-image: login form with Submit"))
        self.assertTrue(wants_qwen_image("a poster with the heading SALE"))
        self.assertTrue(wants_qwen_image("UI mockup of a settings screen"))
        self.assertTrue(wants_qwen_image("a red button labeled Start"))
        self.assertFalse(wants_qwen_image("a fox asleep under maple trees"))
        self.assertFalse(wants_qwen_image("modern website hero banner, purple UI"))
        self.assertFalse(wants_qwen_image("cosmic nebula header banner"))
        self.assertEqual(
            qwen_image_prompt_text("qwen-image: login form with Submit"),
            "login form with Submit",
        )

    def test_qwen_image_graph_uses_gguf_not_flux(self):
        graph = build_qwen_image_prompt("qwen-image: a logo that says Tabby")
        self.assertEqual(graph["1"]["class_type"], "UnetLoaderGGUF")
        self.assertEqual(graph["1"]["inputs"]["unet_name"], "qwen-image-Q4_K_M.gguf")
        self.assertEqual(graph["2"]["inputs"]["type"], "qwen_image")
        self.assertEqual(graph["4"]["inputs"]["text"], "a logo that says Tabby")
        self.assertEqual(graph["9"]["inputs"]["steps"], 8)
        self.assertNotEqual(graph["1"]["inputs"].get("ckpt_name"), "flux1-schnell-fp8.safetensors")

    def test_txt2img_still_uses_empty_latent(self):
        graph = build_prompt("a fox asleep under maple trees")
        self.assertEqual(graph["5"]["class_type"], "EmptySD3LatentImage")
        self.assertEqual(graph["6"]["inputs"]["denoise"], 1.0)
        self.assertNotEqual(graph.get("9", {}).get("class_type"), "LoadImage")

    def test_new_prompt_starts_a_new_turn(self):
        from common.gpu_mode import _read_turn

        with temp_generated_dir([]):
            first = begin_image_turn("a red bicycle", force_new=True)
            same = begin_image_turn("a red bicycle", force_new=False)
            self.assertEqual(first, same)
            retry = begin_image_turn("a red bicycle", force_new=True)
            self.assertEqual(first, retry)
            other = begin_image_turn("a blue cat", force_new=True)
            self.assertEqual(_read_turn().get("prompt"), "a blue cat")
            self.assertGreaterEqual(other, first)
            self.assertEqual(turn_images_ready("missing prompt", 5), [])

    def test_gallery_thumb_is_jpeg_and_capped(self):
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (800, 600), (10, 20, 30)).save(buf, "PNG")
        png = buf.getvalue()
        with temp_generated_dir([]):
            from common import gpu_mode as gm

            src = gm.GENERATED_DIR / "generated-20260101-000001.png"
            src.write_bytes(png)
            dest = ensure_gallery_thumb(src)
            self.assertIsNotNone(dest)
            self.assertEqual(dest.name, "generated-20260101-000001.jpg")
            self.assertEqual(dest.parent.name, "thumbs")
            with Image.open(dest) as im:
                self.assertEqual(im.format, "JPEG")
                self.assertLessEqual(max(im.size), GALLERY_THUMB_MAX)
                self.assertEqual(im.size, (GALLERY_THUMB_MAX, 360))
            self.assertEqual(
                generated_thumb_path("generated-20260101-000001.jpg"), dest
            )
            self.assertEqual(
                generated_thumb_path("generated-20260101-000001.png"), dest
            )
            self.assertIsNone(generated_thumb_path("../secret.png"))
            self.assertIsNone(generated_thumb_path("thumbs/generated-20260101-000001.jpg"))
            self.assertEqual(
                gallery_thumb_href("generated-20260101-000001.png"),
                "thumbs/generated-20260101-000001.jpg",
            )
            self.assertNotIn(
                "thumbs", [path.name for path in list_generated_files()]
            )

    def test_gallery_thumb_reuses_cache_until_source_changes(self):
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (64, 64), (1, 2, 3)).save(buf, "PNG")
        with temp_generated_dir([]):
            from common import gpu_mode as gm

            src = gm.GENERATED_DIR / "generated-20260101-000002.png"
            src.write_bytes(buf.getvalue())
            dest = ensure_gallery_thumb(src)
            first = dest.stat().st_mtime
            time.sleep(0.02)
            again = ensure_gallery_thumb(src)
            self.assertEqual(again.stat().st_mtime, first)
            later = time.time() + 10
            os.utime(src, (later, later))
            refreshed = ensure_gallery_thumb(src)
            self.assertGreater(refreshed.stat().st_mtime, first)

    def test_save_generated_image_writes_a_thumb(self):
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (80, 60), (9, 8, 7)).save(buf, "PNG")
        with temp_generated_dir([]):
            dest = save_generated_image(buf.getvalue())
            thumb = dest.parent / "thumbs" / f"{dest.stem}.jpg"
            self.assertTrue(thumb.is_file())
            with Image.open(thumb) as im:
                self.assertEqual(im.format, "JPEG")


class ServerOwnedMixedJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._sleep = mock.patch(
            "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
        )
        self._slept = self._sleep.start()

    async def asyncTearDown(self):
        self._sleep.stop()

    def _running_job(self):
        return mock.Mock(
            id="job-new",
            status="running",
            wait_text="About 4 minutes.",
            wait_s=280,
            output_path="images/logo.png",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )

    async def test_mixed_user_line_starts_job_and_does_not_reach_llm(self):
        job = self._running_job()
        state = {"job": None}

        async def fake_start(**kwargs):
            state["job"] = job
            job.items = kwargs.get("items") or []
            return job, "started"

        data = _chat(
            "create a webpage and generate a header image and a logo for it"
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                side_effect=lambda: state["job"],
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ) as slept,
        ):
            response = await prepare_mixed_image_turn(
                data, api_base="https://gpu.example/v1"
            )
        start.assert_awaited_once()
        kwargs = start.await_args.kwargs
        self.assertTrue(kwargs["restore"])
        dests = [row["output_path"] for row in kwargs["items"]]
        self.assertIn("images/logo.png", dests)
        self.assertIn("images/header.png", dests)
        slept.assert_awaited()
        self.assertIsNotNone(response)
        self.assertEqual(
            response.choices[0].message.tool_calls[0].function.name, "Shell"
        )
        self.assertIn(
            "sleep ", response.choices[0].message.tool_calls[0].function.arguments
        )
        self.assertNotIn(
            "curl ", response.choices[0].message.tool_calls[0].function.arguments
        )

    async def test_ide_title_request_does_not_start_a_bogus_job(self):
        """GitHub Copilot/Cursor send a separate 'write a title' completion
        that echoes the user's own request verbatim. That echoed text can
        match the logo-redo pattern just like the real ask, which queued a
        second, unwanted render (see mcp_jobs.json job df6dfb93: two items,
        one for the title request, one for the real ask)."""
        title_request = (
            "Please write a brief title for the following request: delete "
            "the current logo.png and create a new logo png image, it "
            "should be an image of an atom with electrons swirling around "
            "it and be transparent background and rectangle not square"
        )
        data = _chat(title_request)
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                new=mock.AsyncMock(),
            ) as start,
        ):
            result = await ensure_mixed_image_job(data)
        self.assertIsNone(result)
        start.assert_not_awaited()

    async def test_matching_job_is_not_started_again(self):
        job = self._running_job()
        data = _chat(
            "create a webpage and generate a header and logo images for it"
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=job
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                new=mock.AsyncMock(),
            ) as start,
        ):
            result = await ensure_mixed_image_job(data)
        self.assertIs(result, job)
        start.assert_not_awaited()

    async def test_await_busy_sleeps_then_returns_wait_tool(self):
        job = self._running_job()
        data = _chat(
            "create a webpage and generate a header and logo images for it",
            tools=["get_image_job"],
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=job
            ),
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ) as slept,
        ):
            response = await await_gpu_busy_image_response(data)
        slept.assert_awaited()
        self.assertEqual(
            response.choices[0].message.tool_calls[0].function.name, "get_image_job"
        )

    async def test_saved_job_lets_coding_model_run(self):
        item = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/a.png"],
            prompt="logo",
            status="done",
            error="",
            count=1,
        )
        job = mock.Mock(
            id="job-done",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/a.png"],
            client_saved=True,
            download_attempts=1,
            error="",
        )
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content=(
                        "create a webpage and generate a header and logo "
                        "images for it"
                    ),
                ),
                ChatCompletionMessage(
                    role="assistant",
                    content="Wrote index.html pointing at images/logo.png",
                ),
                ChatCompletionMessage(
                    role="user",
                    content="now actually create the page in the project",
                ),
            ]
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                new=mock.AsyncMock(),
            ) as start,
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ) as slept,
        ):
            response = await prepare_mixed_image_turn(data)
        start.assert_not_awaited()
        slept.assert_not_awaited()
        self.assertIsNone(response)

    async def test_stale_saved_job_does_not_block_waited_download(self):
        """A leftover done+saved job must not hide this chat's unsaved batch."""
        stale = mock.Mock(
            id="job-stale",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[],
            urls=["https://gpu.example/v1/images/stale.png"],
            client_saved=True,
            download_attempts=1,
            error="",
        )
        current = mock.Mock(
            id="job-current",
            status="done",
            wait_text="About 20 minutes.",
            wait_s=1200,
            output_path="llm-testing/images/logo.png",
            items=[
                mock.Mock(
                    output_path="llm-testing/images/logo.png",
                    urls=["https://gpu.example/v1/images/logo.png"],
                    prompt="logo",
                    status="done",
                    error="",
                    count=1,
                )
            ],
            urls=["https://gpu.example/v1/images/logo.png"],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        data = _with_job_wait(
            _chat(
                "create a website for Cosmos Tours with a nice logo image and "
                "transparent PNG images of Mars, Jupiter, Saturn and Neptune. "
                "Put files under llm-testing.",
                tools=["run_in_terminal"],
            ),
            current.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[current, stale],
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=stale
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                new=mock.AsyncMock(),
            ) as start,
        ):
            response = await gpu_busy_image_response(data)
        start.assert_not_awaited()
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("curl ", args)
        self.assertIn("llm-testing/images/logo.png", args)
        self.assertNotIn("stale.png", args)

    async def test_done_unsaved_job_this_chat_waited_on_curls_once(self):
        item = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/a.png"],
            prompt="logo",
            status="done",
            error="",
            count=1,
        )
        job = mock.Mock(
            id="job-done",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/a.png"],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        data = _with_job_wait(
            _chat(
                "create a webpage and generate a header and logo images for it"
            ),
            job.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                new=mock.AsyncMock(),
            ) as start,
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ) as slept,
        ):
            response = await prepare_mixed_image_turn(data)
        start.assert_not_awaited()
        slept.assert_not_awaited()
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("curl ", args)
        self.assertIn("images/logo.png", args)

    async def test_leftover_done_job_does_not_hijack_a_fresh_mixed_ask(self):
        leftover = mock.Mock(
            id="job-old-pbptours",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="pbptours/images/logo.png",
            items=[],
            urls=["https://gpu.example/v1/images/generated-20260822-000945-234740.png"],
            client_saved=False,
            download_attempts=3,
            error="",
        )
        new_job = mock.Mock(
            id="job-new",
            status="running",
            wait_text="About 4 minutes.",
            wait_s=280,
            output_path="pbptours/images/logo.png",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )
        state = {"job": None}

        async def fake_start(**kwargs):
            state["job"] = new_job
            return new_job, "started"

        data = _chat(
            "create a one page website , the site is a solar systme tours "
            "booking page where people can visit other plantes. I want a nice "
            'logo image for the company "Planet By Planet Tours". I want a bit '
            "of information on each planet along with an image of each planet "
            "and what it has to offer. The entire site should be placed under "
            "the folder pbptours. all images generated should be placed in the "
            "pbptours/images folder."
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                side_effect=lambda: state["job"],
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job",
                side_effect=lambda: state["job"] or leftover,
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ),
        ):
            response = await prepare_mixed_image_turn(
                data, api_base="https://gpu.example/v1"
            )
        start.assert_awaited_once()
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("sleep ", args)
        self.assertNotIn("curl ", args)
        self.assertNotIn("generated-20260822-000945-234740.png", args)

    async def test_tool_result_does_not_start_a_job(self):
        data = ChatCompletionRequest(
            messages=[
                ChatCompletionMessage(
                    role="user",
                    content="create a webpage and generate a logo for it",
                ),
                ChatCompletionMessage(role="tool", content="ok"),
            ]
        )
        with mock.patch(
            "endpoints.core.image_jobs.start_mcp_image_job",
            new=mock.AsyncMock(),
        ) as start:
            result = await ensure_mixed_image_job(data)
        self.assertIsNone(result)
        start.assert_not_awaited()

    async def test_logo_redo_does_not_reuse_a_saved_site_job(self):
        leftover = mock.Mock(
            id="40093aa5-669f-4ec1-9046-a4ec5f63b681",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="pbptours/images/logo.png",
            items=[],
            urls=[
                "https://gpu.example/v1/images/generated-20260822-021552-239881.png",
            ],
            client_saved=True,
            download_attempts=1,
            error="",
        )
        new_job = mock.Mock(
            id="job-redo",
            status="running",
            wait_text="About 3 minutes.",
            wait_s=180,
            output_path="pbptours/images/logo.png",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )
        state = {"job": None}

        async def fake_start(**kwargs):
            state["started"] = kwargs
            state["job"] = new_job
            return new_job, "started"

        page = (
            "create a one page website under the folder pbptours and generate "
            'a logo image for the company "Planet By Planet Tours" and an '
            "image of each planet."
        )
        data = _with_job_wait(_chat(page), leftover.id)
        data.messages.append(
            ChatCompletionMessage(
                role="user",
                content=(
                    "generate the logo image, it should be an image of an atom "
                    "with electrons swirling around it and be transparent "
                    "background and rectangle not square"
                ),
            )
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                side_effect=lambda: state["job"],
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job",
                side_effect=lambda: state["job"] or leftover,
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ),
        ):
            response = await prepare_mixed_image_turn(
                data, api_base="https://gpu.example/v1"
            )
        start.assert_awaited_once()
        items = state["started"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["output_path"], "pbptours/images/logo.png")
        self.assertIn("atom", items[0]["prompt"].lower())
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("sleep ", args)
        self.assertNotIn("curl ", args)
        self.assertNotIn("generated-20260822-021552-239881.png", args)

    async def test_website_spec_logo_should_be_is_not_a_redo(self):
        """'The logo should be large' inside a full site spec used to match
        IMAGE_REDO_RE, so ensure_mixed_image_job queued only images/logo.png.
        Job e428f7b0 on the GPU host was that failure: one Qwen logo, then
        invented planet URLs, HTTP 404, Pillow."""
        spec = (
            'Create a complete, production-ready website for a solar system '
            'tour company called "Cosmos Tours." The website should be a '
            "single-page application. The logo should be large and "
            "prominently displayed. Package section displaying tours to "
            "different planets (Mars, Jupiter, Saturn, Neptune, etc.). "
            "Each planet package should have a generated transparent PNG "
            "image of that planet."
        )
        self.assertFalse(_text_is_image_redo(spec))
        self.assertTrue(is_mixed_image_request(_chat(spec)))
        self.assertTrue(
            _text_is_image_redo(
                "delete the current logo.png and create a new logo png image, "
                "it should be an image of an atom with electrons"
            )
        )

        new_job = mock.Mock(
            id="job-cosmos-full",
            status="queued",
            wait_text="About 17 minutes.",
            wait_s=1114,
            output_path="images/logo.png",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )

        async def fake_start(**kwargs):
            paths = [row.get("output_path") for row in (kwargs.get("items") or [])]
            self.assertEqual(
                paths,
                [
                    "images/logo.png",
                    "images/mars.png",
                    "images/jupiter.png",
                    "images/saturn.png",
                    "images/neptune.png",
                ],
            )
            return new_job, "started"

        data = _chat(spec)
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                return_value=None,
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job",
                return_value=None,
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[],
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
        ):
            job = await ensure_mixed_image_job(
                data, api_base="https://git.pbptech.com/openai/v1"
            )
        start.assert_awaited_once()
        self.assertIs(job, new_job)

    async def test_logo_only_job_does_not_block_missing_planet_dests(self):
        """Once the chat waited on a logo-only job, reuse used to skip the
        covers check. Re-running the Cosmos prompt then never queued planets."""
        leftover = mock.Mock(
            id="e428f7b0-4cc5-4eff-925a-ba730aaccfba",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[
                mock.Mock(
                    output_path="images/logo.png",
                    urls=[
                        "https://git.pbptech.com/openai/v1/images/"
                        "generated-20260823-053850-313512.png"
                    ],
                    prompt="logo that says Cosmos Tours",
                    status="done",
                    error="",
                    count=1,
                )
            ],
            urls=[
                "https://git.pbptech.com/openai/v1/images/"
                "generated-20260823-053850-313512.png"
            ],
            client_saved=False,
            download_attempts=1,
            error="",
        )
        new_job = mock.Mock(
            id="job-planets",
            status="queued",
            wait_text="About 17 minutes.",
            wait_s=1114,
            output_path="images/mars.png",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )

        async def fake_start(**kwargs):
            paths = [row.get("output_path") for row in (kwargs.get("items") or [])]
            self.assertIn("images/mars.png", paths)
            self.assertIn("images/neptune.png", paths)
            self.assertGreaterEqual(len(paths), 5)
            return new_job, "started"

        spec = (
            'Create a complete, production-ready website for a solar system '
            'tour company called "Cosmos Tours." The logo should be large. '
            "Tours to Mars, Jupiter, Saturn, Neptune. Each planet package "
            "should have a generated transparent PNG image of that planet."
        )
        data = _with_job_wait(_chat(spec), leftover.id)
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                return_value=None,
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job",
                return_value=leftover,
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[leftover],
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
        ):
            job = await ensure_mixed_image_job(
                data, api_base="https://git.pbptech.com/openai/v1"
            )
        start.assert_awaited_once()
        self.assertIs(job, new_job)

    async def test_logo_redo_downloads_its_own_job_once_done(self):
        """'delete the current logo.png and create a new logo png image ...
        atom with electrons ...' matches IMAGE_REDO_RE, and it stays the last
        user message for the whole wait loop (no new user text is sent while
        Comfy renders). gpu_busy_image_response must still drive the
        download once *this chat's own* job finishes, not treat it as a
        stale leftover just because the ask looks like a redo."""
        item = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/generated-atom.png"],
            prompt="atom with electrons",
            status="done",
            error="",
        )
        job = mock.Mock(
            id="1555fa7c-7476-443a-8362-50e861504e91",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/generated-atom.png"],
            client_saved=False,
            download_attempts=0,
            error="",
        )
        ask = (
            "delete the current logo.png and create a new logo png image, "
            "it should be an image of an atom with electrons swirling "
            "around it and be transparent background and rectangle not "
            "square"
        )
        data = _chat(ask, tools=["Shell"])
        data.messages.append(
            ChatCompletionMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        function=Tool(
                            name="Shell",
                            arguments=(
                                '{"command":"sleep 20; echo job '
                                f"'{job.id}' still running; ls -l -- "
                                "'images/logo.png'\"}"
                            ),
                        ),
                        type="function",
                    )
                ],
            )
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(data)
        self.assertIsNotNone(response)
        calls = response.choices[0].message.tool_calls
        self.assertEqual(calls[0].function.name, "Shell")
        args = calls[0].function.arguments
        self.assertIn("curl -fsSL", args)
        self.assertIn("images/logo.png", args)
        self.assertIn("generated-atom.png", args)
        self.assertFalse(job.client_saved)

    async def test_folderless_leftover_does_not_curl_on_a_fresh_mixed_ask(self):
        leftover = mock.Mock(
            id="274c874c-old",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[
                mock.Mock(
                    output_path="images/logo.png",
                    urls=[
                        "https://git.pbptech.com/openai/v1/images/"
                        "generated-20260822-214723-251774.png"
                    ],
                    prompt="logo",
                    status="done",
                    error="",
                    count=1,
                )
            ],
            urls=[
                "https://git.pbptech.com/openai/v1/images/"
                "generated-20260822-214723-251774.png"
            ],
            client_saved=False,
            download_attempts=1,
            error="",
        )
        new_job = mock.Mock(
            id="job-new-cosmos",
            status="running",
            wait_text="About 4 minutes.",
            wait_s=280,
            output_path="images/logo.png",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )
        state = {"job": None}

        async def fake_start(**kwargs):
            state["job"] = new_job
            return new_job, "started"

        data = _chat(
            "create a one page website for Cosmos Tours with a nice logo image"
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                side_effect=lambda: state["job"],
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job",
                side_effect=lambda: state["job"] or leftover,
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                side_effect=lambda: [state["job"] or leftover],
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ),
        ):
            response = await prepare_mixed_image_turn(
                data, api_base="https://git.pbptech.com/openai/v1"
            )
        start.assert_awaited_once()
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("sleep ", args)
        self.assertNotIn("curl ", args)
        self.assertNotIn("generated-20260822-214723-251774.png", args)

    async def test_incomplete_running_mcp_job_does_not_block_planned_batch(self):
        """A one-item generate_image dump must not skip the planned planet dests."""
        running = mock.Mock(
            id="job-mcp-dump",
            status="running",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[
                mock.Mock(
                    output_path="images/logo.png",
                    urls=[],
                    prompt="qwen-image: Create a complete production-ready website",
                    status="running",
                    error="",
                    count=1,
                )
            ],
            urls=[],
            client_saved=False,
            error="",
        )
        new_job = mock.Mock(
            id="job-planned",
            status="queued",
            wait_text="About 17 minutes.",
            wait_s=1114,
            output_path="images/",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )

        async def fake_start(**kwargs):
            paths = [row.get("output_path") for row in (kwargs.get("items") or [])]
            self.assertIn("images/logo.png", paths)
            self.assertIn("images/mars.png", paths)
            self.assertGreaterEqual(len(paths), 5)
            return new_job, "started"

        data = _chat(
            'create a website for a company called "Cosmos Tours" with a '
            "logo and transparent PNG images of Mars, Jupiter, Saturn and Neptune"
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                return_value=running,
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job",
                return_value=running,
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[running],
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
        ):
            job = await ensure_mixed_image_job(
                data, api_base="https://git.pbptech.com/openai/v1"
            )
        start.assert_awaited_once()
        self.assertIs(job, new_job)

    async def test_this_chats_dead_gpu_files_requeue_once(self):
        dead_url = (
            "https://gpu.example/v1/images/generated-20260822-214723-251774.png"
        )
        leftover = mock.Mock(
            id="job-dead-own",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[
                mock.Mock(
                    output_path="images/logo.png",
                    urls=[dead_url],
                    prompt="logo",
                    status="done",
                    error="",
                    count=1,
                )
            ],
            urls=[dead_url],
            client_saved=False,
            download_attempts=1,
            error="",
            dead_requeued=False,
            is_requeue=False,
        )
        new_job = mock.Mock(
            id="job-requeued",
            status="running",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[],
            urls=[],
            client_saved=False,
            error="",
        )
        state = {"job": None}

        async def fake_start(**kwargs):
            state["job"] = new_job
            return new_job, "started"

        data = _with_job_wait(
            _chat("create a webpage and generate a logo image for it"),
            leftover.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job",
                side_effect=lambda: state["job"],
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job",
                side_effect=lambda: state["job"] or leftover,
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                side_effect=lambda: [state["job"] or leftover],
            ),
            mock.patch(
                "endpoints.core.image_jobs.start_mcp_image_job",
                side_effect=fake_start,
            ) as start,
            mock.patch(
                "common.phrase_switch.asyncio.sleep", new=mock.AsyncMock()
            ),
            mock.patch("common.gpu_mode.generated_image_path", return_value=None),
        ):
            response = await prepare_mixed_image_turn(data)
        start.assert_awaited_once()
        self.assertTrue(leftover.dead_requeued)
        self.assertTrue(new_job.is_requeue)
        args = response.choices[0].message.tool_calls[0].function.arguments
        self.assertIn("sleep ", args)
        self.assertNotIn("curl ", args)
        self.assertNotIn("generated-20260822-214723-251774.png", args)

    async def test_missing_timestamped_gpu_file_is_not_curled(self):
        dead_url = (
            "https://gpu.example/v1/images/generated-20260822-214723-251774.png"
        )
        job = mock.Mock(
            id="job-missing-png",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[
                mock.Mock(
                    output_path="images/logo.png",
                    urls=[dead_url],
                    prompt="logo",
                    status="done",
                    error="",
                    count=1,
                )
            ],
            urls=[dead_url],
            client_saved=False,
            download_attempts=1,
            error="",
        )
        data = _with_job_wait(
            _chat("create a webpage and generate a logo image for it"),
            job.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[job],
            ),
            mock.patch("common.gpu_mode.generated_image_path", return_value=None),
        ):
            response = await gpu_busy_image_response(data)
        self.assertFalse(response.choices[0].message.tool_calls)
        self.assertNotIn(
            "generated-20260822-214723-251774.png",
            response.choices[0].message.content or "",
        )
        self.assertTrue(job.download_stopped)

    async def test_assistant_404_without_tool_role_does_not_sleep_loop(self):
        item = mock.Mock(
            output_path="images/logo.png",
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            prompt="logo",
            status="done",
            error="",
            count=1,
        )
        job = mock.Mock(
            id="job-done",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[item],
            urls=["https://gpu.example/v1/images/generated-logo.png"],
            client_saved=False,
            download_attempts=1,
            error="",
        )
        data = _with_job_wait(
            _chat(
                "create a webpage and generate a logo image for it",
                tools=["run_in_terminal"],
            ),
            job.id,
        )
        data.messages.append(
            ChatCompletionMessage(
                role="assistant",
                content=(
                    "curl: (22) The requested URL returned error: 404\n"
                    "https://gpu.example/v1/images/generated-logo.png"
                ),
            )
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=job
            ),
        ):
            response = await gpu_busy_image_response(data)
            self.assertFalse(response.choices[0].message.tool_calls)
            text = response.choices[0].message.content or ""
            self.assertNotIn("sleep ", text)
            self.assertTrue(job.download_stopped)
            self.assertIn("https://gpu.example/v1/images/generated-logo.png", text)

            again = await gpu_busy_image_response(data)
        self.assertIsNone(again)

    def test_pngs_ready_false_for_global_leftover_done_job(self):
        leftover = mock.Mock(
            id="job-global-leftover",
            status="done",
            wait_text="About 4 minutes.",
            wait_s=240,
            output_path="images/logo.png",
            items=[],
            urls=[
                "https://gpu.example/v1/images/generated-20260822-214723-251774.png"
            ],
            client_saved=False,
            download_attempts=1,
            error="",
        )
        data = _chat("create a webpage and generate a logo image for it")
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=leftover
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[leftover],
            ),
        ):
            inject_mixed_image_hint(data, api_base="https://gpu.example/v1")
        hint = data.messages[0].content
        self.assertNotIn("The GPU PNGs already exist", hint)

        leftover.client_saved = True
        waited = _with_job_wait(
            _chat("create a webpage and generate a logo image for it"),
            leftover.id,
        )
        with (
            mock.patch(
                "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
            ),
            mock.patch(
                "endpoints.core.image_jobs.get_mcp_image_job", return_value=leftover
            ),
            mock.patch(
                "endpoints.core.image_jobs.recent_mcp_image_jobs",
                return_value=[leftover],
            ),
        ):
            inject_mixed_image_hint(waited, api_base="https://gpu.example/v1")
        self.assertIn(
            "The GPU PNGs already exist", waited.messages[0].content
        )

    def test_is_public_generated_png(self):
        from common.gpu_mode import is_public_generated_png

        self.assertTrue(
            is_public_generated_png("generated-20260822-214723-251774.png")
        )
        self.assertFalse(is_public_generated_png("generated-latest.png"))
        self.assertFalse(is_public_generated_png("generated-logo.png"))
        self.assertFalse(is_public_generated_png("latest.png"))

    async def test_timestamped_png_get_without_bearer(self):
        from endpoints.core.router import generated_image

        name = "generated-20260822-214723-251774.png"
        with temp_generated_dir([name]):
            response = await generated_image(name)
        self.assertEqual(response.media_type, "image/png")
        self.assertTrue(str(response.path).endswith(name))

    async def test_gallery_checkboxes_toggle_instead_of_radio(self):
        from endpoints.core.router import generated_images_index

        with temp_generated_dir(["generated-20260101-000001.png"]):
            response = await generated_images_index()
        html = bytes(response.body).decode("utf-8")
        self.assertIn('type="checkbox"', html)
        self.assertNotIn("other.checked=k===i", html)
        self.assertIn("box.addEventListener('change',paint)", html)


if __name__ == "__main__":
    unittest.main()

import unittest

from common.agent_loop import inject_loop_break, looks_like_tool_loop
from endpoints.OAI.types.chat_completion import ChatCompletionMessage, ChatCompletionRequest
from endpoints.OAI.types.tools import Tool, ToolCall


def msg(role, content=None, name=None, args='{"path":"a.py"}'):
    calls = None
    if name:
        calls = [ToolCall(function=Tool(name=name, arguments=args))]
    return ChatCompletionMessage(role=role, content=content, tool_calls=calls)


class AgentLoopTests(unittest.TestCase):
    def test_short_history_is_not_a_loop(self):
        data = ChatCompletionRequest(
            messages=[
                msg("user", "fix it"),
                msg("assistant", name="Read"),
                msg("tool", "ok"),
            ]
        )
        self.assertFalse(looks_like_tool_loop(data))

    def test_three_identical_reads_are_a_loop(self):
        data = ChatCompletionRequest(
            messages=[
                msg("user", "fix it"),
                msg("assistant", name="Read", args='{"path":"a.py"}'),
                msg("tool", "1"),
                msg("assistant", name="Read", args='{"path":"a.py"}'),
                msg("tool", "2"),
                msg("assistant", name="Read", args='{"path":"a.py"}'),
            ]
        )
        self.assertTrue(looks_like_tool_loop(data))
        self.assertTrue(inject_loop_break(data))
        self.assertTrue(data.messages[-1].content.startswith("[Anti-loop]"))
        self.assertFalse(inject_loop_break(data))

    def test_eight_greps_are_a_loop(self):
        messages = [msg("user", "explore")]
        for index in range(8):
            messages.append(msg("assistant", name="Grep", args=f'{{"pattern":"x{index}"}}'))
            messages.append(msg("tool", "hit"))
        self.assertTrue(looks_like_tool_loop(ChatCompletionRequest(messages=messages)))

    def test_get_image_job_polls_are_not_a_loop(self):
        from unittest import mock

        messages = [msg("user", "make a site with a logo")]
        for _ in range(6):
            messages.append(
                msg("assistant", name="get_image_job", args='{"job_id":"abc","wait_s":20}')
            )
            messages.append(msg("tool", "running"))
        data = ChatCompletionRequest(messages=messages)
        with mock.patch(
            "endpoints.core.image_jobs.active_mcp_image_job", return_value=object()
        ):
            self.assertFalse(looks_like_tool_loop(data))

    def test_get_image_job_after_job_finishes_is_a_loop(self):
        from unittest import mock

        messages = [msg("user", "make a site with a logo")]
        for _ in range(3):
            messages.append(
                msg("assistant", name="get_image_job", args='{"job_id":"abc","wait_s":20}')
            )
            messages.append(msg("tool", "Job abc: done"))
        data = ChatCompletionRequest(messages=messages)
        with mock.patch(
            "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
        ):
            self.assertTrue(looks_like_tool_loop(data))
            self.assertTrue(inject_loop_break(data))
        self.assertIn("image job is finished", data.messages[-1].content)

    def test_shell_wait_polls_are_not_a_loop(self):
        """Clients without get_image_job invent an identical Shell sleep+ls
        wait command every turn (see image_paths.image_poll_wait_command).
        That must not fire the anti-loop hint while the job is still
        running — the hint text tells the model to stop and "give a short
        status now", which stomps the image-wait turn and corrupts the
        last-user-message context every image helper relies on."""
        from unittest import mock

        wait_args = (
            '{"command":"sleep 20; echo job \'df6dfb93-0da5-41ec-8a03-e118d42817d2\' '
            "still running; ls -l -- 'images/logo.png' 2>/dev/null || echo existing none\"}"
        )
        messages = [msg("user", "delete logo.png and make a new one, an atom")]
        for _ in range(8):
            messages.append(msg("assistant", name="run_in_terminal", args=wait_args))
            messages.append(msg("tool", "job df6dfb93 still running\nexisting none"))
        data = ChatCompletionRequest(messages=messages)
        with mock.patch(
            "endpoints.core.image_jobs.active_mcp_image_job", return_value=object()
        ):
            self.assertFalse(looks_like_tool_loop(data))
            self.assertFalse(inject_loop_break(data))
        self.assertEqual(data.messages[-1].role, "tool")

    def test_shell_wait_polls_after_job_finishes_is_a_loop(self):
        from unittest import mock

        wait_args = (
            '{"command":"sleep 20; echo job \'abc\' still running; '
            "ls -l -- 'images/logo.png' 2>/dev/null || echo existing none\"}"
        )
        messages = [msg("user", "delete logo.png and make a new one, an atom")]
        for _ in range(3):
            messages.append(msg("assistant", name="run_in_terminal", args=wait_args))
            messages.append(msg("tool", "job abc still running"))
        data = ChatCompletionRequest(messages=messages)
        with mock.patch(
            "endpoints.core.image_jobs.active_mcp_image_job", return_value=None
        ):
            self.assertTrue(looks_like_tool_loop(data))
            self.assertTrue(inject_loop_break(data))

    def test_unrelated_repeated_shell_command_is_still_a_loop(self):
        """A repeated Shell call that does not match our wait fingerprint,
        even with an active image job elsewhere, must still be caught."""
        from unittest import mock

        messages = [msg("user", "fix it")]
        for _ in range(3):
            messages.append(
                msg("assistant", name="run_in_terminal", args='{"command":"npm test"}')
            )
            messages.append(msg("tool", "2 failing"))
        data = ChatCompletionRequest(messages=messages)
        with mock.patch(
            "endpoints.core.image_jobs.active_mcp_image_job", return_value=object()
        ):
            self.assertTrue(looks_like_tool_loop(data))

    def test_edit_resets_search_streak(self):
        messages = [msg("user", "edit")]
        for index in range(3):
            messages.append(msg("assistant", name="Grep", args=f'{{"pattern":"y{index}"}}'))
            messages.append(msg("tool", "hit"))
        messages.append(msg("assistant", name="Write", args='{"path":"a.py"}'))
        messages.append(msg("tool", "ok"))
        self.assertFalse(looks_like_tool_loop(ChatCompletionRequest(messages=messages)))


if __name__ == "__main__":
    unittest.main()

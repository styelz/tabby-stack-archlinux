import json
import unittest

from common.noop_edits import (
    is_noop_edit,
    split_noop_tool_dumps,
    patch_is_noop,
    tool_result_is_zero_change,
)


class NoopEditsTests(unittest.TestCase):
    def test_identical_strreplace_is_noop(self):
        css = ".hero { color: red; }"
        self.assertTrue(
            is_noop_edit(
                "StrReplace",
                {"path": "a.css", "old_string": css, "new_string": css},
            )
        )

    def test_real_strreplace_is_kept(self):
        self.assertFalse(
            is_noop_edit(
                "StrReplace",
                {
                    "path": "a.css",
                    "old_string": ".hero { color: red; }",
                    "new_string": ".hero { color: blue; }",
                },
            )
        )

    def test_json_arguments_string(self):
        args = json.dumps({"old_string": "a", "new_string": "a"})
        self.assertTrue(is_noop_edit("search_replace", args))

    def test_empty_patch_is_noop(self):
        patch = "*** Begin Patch\n*** Update File: a.css\n*** End Patch"
        self.assertTrue(patch_is_noop(patch))
        self.assertTrue(is_noop_edit("ApplyPatch", {"input": patch}))

    def test_identity_hunk_is_noop(self):
        patch = "--- a.css\n+++ a.css\n@@\n-color: red;\n+color: red;\n"
        self.assertTrue(is_noop_edit("apply_patch", {"patch": patch}))

    def test_real_hunk_is_kept(self):
        patch = "@@\n-color: red;\n+color: blue;\n"
        self.assertFalse(is_noop_edit("ApplyPatch", {"input": patch}))

    def test_read_is_never_noop(self):
        self.assertFalse(is_noop_edit("Read", {"path": "a.css"}))

    def test_split_drops_only_noops(self):
        dumped = [
            {
                "index": 0,
                "function": {
                    "name": "StrReplace",
                    "arguments": json.dumps(
                        {"old_string": "x", "new_string": "x"}
                    ),
                },
            },
            {
                "index": 1,
                "function": {
                    "name": "Read",
                    "arguments": json.dumps({"path": "a.css"}),
                },
            },
        ]
        kept, dropped = split_noop_tool_dumps(dumped)
        self.assertEqual(dropped, 1)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["function"]["name"], "Read")
        self.assertEqual(kept[0]["index"], 0)

    def test_zero_change_tool_result(self):
        self.assertTrue(tool_result_is_zero_change("Applied edit to a.css (0 changes)."))
        self.assertFalse(tool_result_is_zero_change("Updated a.css"))

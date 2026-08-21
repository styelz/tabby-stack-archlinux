import re
import json
from common.logger import xlogger
from endpoints.OAI.types.tools import ToolCall, Tool
from endpoints.OAI.utils.toolcall_formats.common import coerce_param_value

"""
Qwen3.5 / Qwen3-Coder - pseudo-XML syntax

Raw format:
    <tool_call>
        <function=__FUNCTION_NAME__>
            <parameter=__PARAMETER_NAME_1__>
                __PARAMETER_1__
            </parameter>
            <parameter=__PARAMETER_NAME_2__>
                __PARAMETER_2__
            </parameter>
            ...
        </function>
    </tool_call>
"""

# Qwen 3.5/3.6 often skip the outer <tool_call> wrapper and emit a bare
# <function=...>. The stream parser watches every start tag in TOOLCALL_STARTS
# so those tokens are not leaked as chat. TOOLCALL_ENDS includes </function>
# so a complete bare call can return to content; a missing closer still keeps
# the rest of the turn on the tool channel until EOS. Nested start/end tags
# use a depth count so </function> does not close an outer <tool_call>.

TOOLCALL_START = "<tool_call>"
TOOLCALL_END = "</tool_call>"
TOOLCALL_STARTS = ("<tool_call>", "<function=")
TOOLCALL_ENDS = ("</tool_call>", "</function>")

_FUNC_OPEN = re.compile(r"<function=([^>\s]+)[^>]*>")
_PARAM = re.compile(r"<parameter=([^>\s]+)[^>]*>(.*?)(?:</parameter>|$)", re.DOTALL)
_TRAILING_CLOSE = re.compile(r"</function>|</tool_call>", re.DOTALL)


def _parse_params(body: str) -> dict:
    args: dict[str, any] = {}
    for pm in _PARAM.finditer(body):
        key = pm.group(1).strip()
        val = _TRAILING_CLOSE.split(pm.group(2), maxsplit=1)[0]
        args[key] = coerce_param_value(val)
    return args


def parse_toolcalls(text: str) -> list[ToolCall]:
    # Scan every <function=name> block. Closing </function> / </tool_call>
    # tags are optional so a 2bpw model that stops mid-call still parses.
    results = []
    opens = list(_FUNC_OPEN.finditer(text))
    for i, fm in enumerate(opens):
        func_name = fm.group(1)
        start = fm.end()
        end = opens[i + 1].start() if i + 1 < len(opens) else len(text)
        args = _parse_params(text[start:end])
        args_json = json.dumps(args, ensure_ascii=False)
        results.append(ToolCall(function=Tool(name=func_name, arguments=args_json)))

    xlogger.debug(
        f"qwen3_coder: Parsed {len(results)} tool calls",
        {"raw_text": text, "results": results},
    )
    return results

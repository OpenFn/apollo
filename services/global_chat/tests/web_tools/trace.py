"""Turn the planner's raw API responses into an ordered record of web tool calls.

Test helper only.
"""

from typing import Any

WEB_TOOL_NAMES = {"web_search": "search", "web_fetch": "fetch"}
RESULT_BLOCK_SUFFIX = "_tool_result"


def build_trace(responses: list) -> list[dict]:
    """One entry per server tool call, in the order the model made them.

    Results are paired to calls by tool_use_id across all responses, because a
    pause_turn can split a call from its result.
    """
    calls: list[dict] = []
    by_id: dict[object, dict] = {}

    for round_index, response in enumerate(responses, start=1):
        for block in field(response, "content") or []:
            block_type = field(block, "type")
            if block_type == "server_tool_use":
                name = str(field(block, "name"))
                tool_input = field(block, "input") or {}
                entry = {
                    "round": round_index,
                    "tool": WEB_TOOL_NAMES.get(name, name),
                    "target": tool_input.get("url") or tool_input.get("query") or "",
                    "result": "missing",
                }
                calls.append(entry)
                by_id[field(block, "id")] = entry
            elif str(block_type).endswith(RESULT_BLOCK_SUFFIX):
                entry = by_id.get(field(block, "tool_use_id"))
                if entry is None:
                    continue
                content = field(block, "content")
                entry["result"] = result_code(content)
                if entry["tool"] == "fetch" and entry["result"] == "ok":
                    text = fetched_text(content)
                    entry["content"] = text
                    entry["content_chars"] = len(text) if text is not None else None

    return calls


def count(trace: list[dict], tool: str | None = None, result: str | None = None) -> int:
    """How many calls match the given tool and/or result."""
    return sum(
        1
        for call in trace
        if (tool is None or call["tool"] == tool) and (result is None or call["result"] == result)
    )


def format_trace(trace: list[dict]) -> str:
    """One readable line per call, for failure messages and the runner's output."""
    if not trace:
        return "(no web calls)"
    lines = []
    for call in trace:
        size = f"  {call['content_chars']} chars" if call.get("content_chars") is not None else ""
        lines.append(f"r{call['round']}  {call['tool']:<7} {call['result']:<26} {call['target']}{size}")
    return "\n".join(lines)


def field(obj: object, name: str) -> Any:  # noqa: ANN401
    """Read a field from an SDK block or a plain dict; the unit fakes use both."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def result_code(content: object) -> str:
    """'ok', or the error_code of a failed result. A list is always a search success."""
    if content is None:
        return "missing"
    if isinstance(content, list):
        return "ok"
    if str(field(content, "type") or "").endswith("_error"):
        return str(field(content, "error_code") or "unknown_error")
    return "ok"


def fetched_text(content: object) -> str | None:
    """The plain text of a successful fetch, or None when it is not text (e.g. a PDF)."""
    source = field(field(content, "content"), "source")
    if field(source, "type") != "text":
        return None
    data = field(source, "data")
    return data if isinstance(data, str) else None

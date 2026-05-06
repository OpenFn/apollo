"""Mock Anthropic HTTP client for service tests.

The `test_hooks` dict accepts (all optional; all default to absent):

- "anthropic_http_client": an httpx.Client backed by httpx.MockTransport.
  When present, threaded into every Anthropic(...) constructor site via
  `services/util.py::build_anthropic_client`.
- "tool_calls": a list[dict] the test allocates. Production code appends
  breadcrumbs via `services/util.py::record_tool_call`.
- "tool_stubs": dict[str, Callable] keyed by tool name. When the planner
  dispatches a tool, if a stub exists for that name it's called with the
  tool input and its return value is used as the tool result. Today only
  used for "search_documentation".
"""
from __future__ import annotations

import json
import re
import uuid

import httpx


def tool_use(name: str, input: dict, id: str = "toolu_test") -> list[dict]:
    """Build a single tool_use content block for `MockAnthropic.set_response`."""
    return [{"type": "tool_use", "id": id, "name": name, "input": input}]


def _latest_user_text(messages: list[dict]) -> str:
    """Concatenate text + tool_result content from the last user message."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    inner = block.get("content")
                    if isinstance(inner, str):
                        parts.append(inner)
                    elif isinstance(inner, list):
                        for sub in inner:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                parts.append(sub.get("text", ""))
            return "\n".join(parts)
        return ""
    return ""


def _build_message_body(response: str | list[dict]) -> dict:
    """Wrap a registered response as a full Anthropic message envelope."""
    if isinstance(response, str):
        content_blocks = [{"type": "text", "text": response}]
        stop_reason = "end_turn"
    else:
        content_blocks = response
        stop_reason = "tool_use" if any(b.get("type") == "tool_use" for b in response) else "end_turn"

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": "claude-mock",
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


class MockAnthropic:
    """Mock Anthropic API backed by httpx.MockTransport.

    Tests register regex → response pairs. Each request is matched against
    the latest user message text (including tool_result content); the first
    matching pattern wins. No match raises AssertionError.

    Usage:
        mock = MockAnthropic()
        mock.set_response(r"haiku", "sure, here's a haiku")
        mock.set_response(r"create workflow", tool_use("call_workflow_agent", {...}))
        test_hooks = test_hooks_factory(anthropic=mock)
        main(payload, test_hooks)
        assert mock.last_request.headers["x-api-key"] == "sk-test"
    """

    def __init__(self):
        self._responses: list[tuple[re.Pattern, str | list[dict]]] = []
        self.requests: list[httpx.Request] = []

    def set_response(self, pattern: str, response: str | list[dict]) -> None:
        """Register a response for any request whose latest user-message text matches `pattern`.

        `response` is either:
          - str: returned as a single text content block.
          - list[dict]: returned as content blocks (use for tool_use, mixed).
        """
        self._responses.append((re.compile(pattern), response))

    @property
    def httpx_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    @property
    def last_request(self) -> httpx.Request:
        return self.requests[-1]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        user_text = _latest_user_text(body.get("messages", []))
        for pattern, resp in self._responses:
            if pattern.search(user_text):
                return httpx.Response(200, json=_build_message_body(resp))
        raise AssertionError(
            f"MockAnthropic: no pattern matched user message {user_text!r}. "
            f"Registered patterns: {[p.pattern for p, _ in self._responses]}"
        )

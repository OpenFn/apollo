"""Unit tests for page-navigation prefix handling.

`extract_page_prefix_from_last_turn` reads the `[pg:...]` tag off the previous
user turn so job_chat can detect navigation between turns. It pairs with
`add_page_prefix`, which writes that tag when building history. These lock in the
round-trip and the guard against non-string history content (e.g. a stale
planner-format turn whose content is a content-block list).
"""

from job_chat.job_chat import extract_page_prefix_from_last_turn
from util import add_page_prefix

PAGE = {"type": "job_code", "name": "Transform", "adaptor": "http@6.5.4"}


def _turns(user_content):
    return [{"role": "user", "content": user_content}, {"role": "assistant", "content": "ok"}]


def test_extracts_prefix_from_previous_user_turn():
    history = _turns("[pg:job_code/Transform/http@6.5.4] tweak this")
    assert extract_page_prefix_from_last_turn(history) == "[pg:job_code/Transform/http@6.5.4]"


def test_returns_none_when_fewer_than_two_turns():
    assert extract_page_prefix_from_last_turn([]) is None
    assert extract_page_prefix_from_last_turn([{"role": "user", "content": "[pg:x] hi"}]) is None


def test_returns_none_when_no_prefix():
    assert extract_page_prefix_from_last_turn(_turns("just a message")) is None


def test_returns_none_when_content_not_string():
    history = _turns([{"type": "tool_result", "content": "x"}])
    assert extract_page_prefix_from_last_turn(history) is None


def test_roundtrip_with_add_page_prefix():
    history = _turns(add_page_prefix("tweak this", PAGE))
    expected = add_page_prefix("", PAGE).strip()
    assert extract_page_prefix_from_last_turn(history) == expected

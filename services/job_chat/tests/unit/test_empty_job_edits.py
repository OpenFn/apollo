"""Unit tests for writing code into an empty/new job (issue #539).

Before the fix, the assistant silently dropped generated code when the job body
was empty: `generate()` only applied edits `if job_code:`, and
`parse_and_apply_edits()` short-circuited on `not original_code`. The user saw a
preamble ("I'll add a fn()...") with no code.

These exercise the pure edit-application methods. We build the instance with
`__new__` to skip `__init__` (which constructs an Anthropic client, blocked in
unit tests); the `rewrite` path never touches the LLM client.
"""

import json

from job_chat.job_chat import AnthropicClient


def _client():
    return AnthropicClient.__new__(AnthropicClient)


def test_rewrite_into_empty_job_returns_full_code():
    suggested, diff = _client().apply_code_edits(
        content="write a simple http post",
        text_answer="I'll add it",
        original_code="",
        code_edits=[{"action": "rewrite", "new_code": "post('https://x.test', state.data);"}],
    )

    assert suggested == "post('https://x.test', state.data);"
    assert diff["patches_applied"] == 1


def test_replace_action_into_empty_job_writes_code():
    # The model may send a "replace" against an empty job. With nothing to find,
    # the new code is still the result, deterministically and without an LLM
    # error-correction round-trip.
    suggested, diff = _client().apply_code_edits(
        content="write a simple http post",
        text_answer="I'll add it",
        original_code="",
        code_edits=[
            {"action": "replace", "old_code": "// anything", "new_code": "post('https://x.test');"}
        ],
    )

    assert suggested == "post('https://x.test');"
    assert diff["patches_applied"] == 1


def test_whitespace_only_job_treated_as_empty():
    suggested, diff = _client().apply_code_edits(
        content="write a simple http post",
        text_answer="I'll add it",
        original_code="   \n\n  ",
        code_edits=[{"action": "rewrite", "new_code": "post('https://x.test');"}],
    )

    assert suggested == "post('https://x.test');"
    assert diff["patches_applied"] == 1


def test_parse_and_apply_no_longer_drops_code_on_empty_original():
    response = json.dumps(
        {
            "text_answer": "I'll write it",
            "code_edits": [{"action": "rewrite", "new_code": "get('https://x.test');"}],
        }
    )

    text, suggested, diff = _client().parse_and_apply_edits(
        response, content="x", original_code=""
    )

    assert suggested == "get('https://x.test');"
    assert diff["patches_applied"] == 1


def test_no_code_edits_still_returns_none():
    response = json.dumps({"text_answer": "just explaining", "code_edits": []})

    text, suggested, diff = _client().parse_and_apply_edits(
        response, content="x", original_code=""
    )

    assert suggested is None
    assert diff is None

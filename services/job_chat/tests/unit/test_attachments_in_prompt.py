"""Attachments reach the model on the turn they arrived on, and only then."""

from unittest.mock import patch

from job_chat.prompt import build_prompt

LOG = "[JOB] ✗ Request failed with status 401 Unauthorized"

ATTACHMENTS = [{"type": "log", "content": LOG}]


def build(content, history, attachments):
    # RAG is a live network call; the retrieved knowledge is irrelevant here
    with patch("job_chat.prompt.retrieve_knowledge", return_value={"search_results": []}):
        return build_prompt(
            content=content,
            history=history,
            context={},
            attachments=attachments,
        )


def test_attachment_content_reaches_the_current_turn_verbatim():
    _, prompt, _ = build("why did this fail?", [], ATTACHMENTS)

    last_turn = prompt[-1]["content"]
    assert "why did this fail?" in last_turn
    assert LOG in last_turn
    # The edit_job reminder stays the last thing the model reads
    assert last_turn.rstrip().endswith("apply the change.")


def test_attachments_do_not_touch_earlier_turns():
    history = [
        {"role": "user", "content": "what does this step do?"},
        {"role": "assistant", "content": "it posts encounters"},
    ]

    _, prompt, _ = build("and why did it fail?", history, ATTACHMENTS)

    assert LOG not in prompt[0]["content"]
    assert LOG not in prompt[1]["content"]
    assert LOG in prompt[-1]["content"]


def test_no_attachments_changes_nothing():
    _, with_none, _ = build("hello", [], None)
    _, with_empty, _ = build("hello", [], [])

    assert "<attachments>" not in with_none[-1]["content"]
    assert with_none[-1]["content"] == with_empty[-1]["content"]

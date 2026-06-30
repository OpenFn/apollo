"""Unit test for the `has_code_attachment` Langfuse tag (no LLM, no keys).

job_chat.main() should tag the trace with `has_code_attachment` ONLY when the
model actually produced code edits (result.suggested_code is truthy) AND
tracking is on. We mock the LLM seam (AnthropicClient.generate) and spy on
propagate_attributes to capture the tags it is called with.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from job_chat.job_chat import ChatResponse, main


def _fake_response(suggested_code):
    return ChatResponse(
        response="ok",
        suggested_code=suggested_code,
        history=[],
        usage={},
        rag={},
        diff=None,
    )


def _payload(metrics_opt_in=True):
    return {
        "content": "add error handling",
        "context": {"expression": "get('x');", "adaptor": "@openfn/language-http@6.5.1"},
        "suggest_code": True,
        "metrics_opt_in": metrics_opt_in,
        "meta": {"session_id": "s1", "user": {"id": "u1", "persona": "core-contributor"}},
    }


def _run_capturing_tags(suggested_code, metrics_opt_in=True):
    """Run main() with mocked seams; return every `tags` value passed to propagate_attributes."""
    captured = []

    @contextmanager
    def fake_propagate(**kwargs):
        captured.append(kwargs.get("tags"))
        yield

    fake_client = MagicMock()
    fake_client.generate.return_value = _fake_response(suggested_code)

    with patch("job_chat.job_chat.propagate_attributes", side_effect=fake_propagate), \
         patch("job_chat.job_chat.AnthropicClient", return_value=fake_client), \
         patch("job_chat.job_chat.get_langfuse_client", return_value=MagicMock()):
        main(_payload(metrics_opt_in=metrics_opt_in))

    return captured


def test_tag_applied_when_code_generated():
    captured = _run_capturing_tags(suggested_code="newCode();")
    assert ["has_code_attachment"] in captured


def test_tag_absent_when_no_code():
    captured = _run_capturing_tags(suggested_code=None)
    assert ["has_code_attachment"] not in captured


def test_tag_absent_when_not_tracking():
    captured = _run_capturing_tags(suggested_code="newCode();", metrics_opt_in=False)
    assert ["has_code_attachment"] not in captured

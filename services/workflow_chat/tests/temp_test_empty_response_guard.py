"""
Smoke test for the empty-response ApolloError guard.

Verifies that workflow_chat raises ApolloError(502) with the right type
when the LLM produces no usable text, instead of returning HTTP 200 with
response: "" — which would make Lightning's ChatMessage insert fail and
leave the user-side message stuck in :processing.

Run from repo root:
    poetry run pytest services/workflow_chat/tests/test_empty_response_guard.py -v
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).parent.parent.parent))
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

os.environ.setdefault("ANTHROPIC_API_KEY", "fake")

from util import ApolloError  # noqa: E402
from workflow_chat.workflow_chat import main as workflow_main  # noqa: E402


def make_empty_message(stop_reason: str):
    """Mock Anthropic message with no text content blocks."""
    msg = MagicMock()
    msg.content = []
    msg.stop_reason = stop_reason

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_creation_input_tokens = 0
    usage.cache_read_input_tokens = 0
    usage.model_dump = MagicMock(return_value={
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    })
    msg.usage = usage
    return msg


def _payload():
    return {
        "content": "build a workflow",
        "history": [],
        "context": {"page_name": "test"},
        "api_key": "fake",
        "stream": False,
    }


def test_max_tokens_raises_output_truncated():
    """stop_reason=max_tokens with empty content -> 502 OUTPUT_TRUNCATED."""
    with patch("workflow_chat.workflow_chat.Anthropic") as mock_anth:
        mock_client = MagicMock()
        mock_anth.return_value = mock_client
        mock_client.messages.create.return_value = make_empty_message("max_tokens")

        with pytest.raises(ApolloError) as exc_info:
            workflow_main(_payload())

    assert exc_info.value.code == 502
    assert exc_info.value.type == "OUTPUT_TRUNCATED"


def test_end_turn_empty_raises_empty_output():
    """stop_reason=end_turn with no text blocks -> 502 EMPTY_OUTPUT."""
    with patch("workflow_chat.workflow_chat.Anthropic") as mock_anth:
        mock_client = MagicMock()
        mock_anth.return_value = mock_client
        mock_client.messages.create.return_value = make_empty_message("end_turn")

        with pytest.raises(ApolloError) as exc_info:
            workflow_main(_payload())

    assert exc_info.value.code == 502
    assert exc_info.value.type == "EMPTY_OUTPUT"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

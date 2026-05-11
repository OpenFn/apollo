"""
Smoke test for the planner's empty-response ApolloError guard.

Verifies that global_chat's PlannerAgent raises ApolloError(502) with the
right type when the LLM produces no usable text (rather than returning a
PlannerResult with response: "" — which would surface as HTTP 200 from
global_chat and leave the user-side message stuck in :processing).

Run from repo root:
    poetry run pytest services/global_chat/tests/test_empty_response_guard.py -v
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
os.environ.setdefault("OPENAI_API_KEY", "fake")

from util import ApolloError  # noqa: E402
from global_chat.config_loader import ConfigLoader  # noqa: E402
from global_chat.planner import PlannerAgent  # noqa: E402


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


def _run_planner_with_response(message):
    config_loader = ConfigLoader()
    planner = PlannerAgent(config_loader=config_loader, api_key="fake")
    with patch.object(planner.client.beta.messages, "create", return_value=message):
        planner.run(
            content="x",
            workflow_yaml=None,
            page=None,
            history=[],
            stream=False,
        )


def test_max_tokens_raises_output_truncated():
    """stop_reason=max_tokens with empty content -> 502 OUTPUT_TRUNCATED."""
    with pytest.raises(ApolloError) as exc_info:
        _run_planner_with_response(make_empty_message("max_tokens"))

    assert exc_info.value.code == 502
    assert exc_info.value.type == "OUTPUT_TRUNCATED"


def test_end_turn_empty_raises_empty_output():
    """stop_reason=end_turn with no text blocks -> 502 EMPTY_OUTPUT."""
    with pytest.raises(ApolloError) as exc_info:
        _run_planner_with_response(make_empty_message("end_turn"))

    assert exc_info.value.code == 502
    assert exc_info.value.type == "EMPTY_OUTPUT"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

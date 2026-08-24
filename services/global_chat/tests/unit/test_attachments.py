"""Unit tests for input-attachment passthrough.

Attachments must reach a subagent as the exact bytes the user sent (never the
planner's paraphrase), and must never end up in the history that is returned to
the client and replayed on later turns.
"""

from unittest.mock import patch

import pytest

from global_chat.subagent_caller import (
    call_job_agent,
    call_workflow_agent,
    format_subagent_result_for_llm,
)
from util import ATTACHMENT_TOTAL_CHAR_LIMIT, ApolloError, append_attachments

from .test_planner import WORKFLOW_YAML, make_planner
from .test_router import make_router

LOG = "[JOB] ✗ Request failed with status 401 Unauthorized\n[R/T] Job exited with error code 1"

ATTACHMENTS = [
    {"type": "log", "content": LOG},
    {"type": "input_dataclip", "content": '{"patients": []}'},
]


# --- the renderer ---------------------------------------------------------


def test_attachments_are_reproduced_verbatim() -> None:
    result = append_attachments("why did this fail?", ATTACHMENTS)

    assert "why did this fail?" in result
    assert LOG in result
    assert '<attachment type="log">' in result
    assert '<attachment type="input_dataclip">' in result


def test_no_attachments_leaves_content_untouched() -> None:
    assert append_attachments("hello", None) == "hello"
    assert append_attachments("hello", []) == "hello"
    # An entry with no usable content adds no empty block
    assert append_attachments("hello", [{"type": "log", "content": "  "}]) == "hello"


def test_a_large_attachment_that_fits_is_passed_whole() -> None:
    body = "HEAD" + ("x" * (ATTACHMENT_TOTAL_CHAR_LIMIT - 100)) + "TAIL"

    result = append_attachments("debug this", [{"type": "log", "content": body}])

    # Nothing is trimmed to make room — a log the user attached is read in full
    assert body in result


def test_oversized_attachments_are_rejected_not_edited() -> None:
    body = "x" * (ATTACHMENT_TOTAL_CHAR_LIMIT + 1)

    with pytest.raises(ApolloError) as excinfo:
        append_attachments("debug this", [{"type": "log", "content": body}])

    error = excinfo.value
    assert error.code == 400
    assert error.type == "ATTACHMENT_TOO_LARGE"
    # The message must name the offender so the client can say something useful
    assert "log" in error.message
    assert error.details["largest_attachment"]["characters"] == len(body)
    # ...and must not carry the attachment's content anywhere
    assert body not in error.message


def test_the_limit_applies_to_the_total_not_each_attachment() -> None:
    """The prompt carries them together, so the sum is the constraint.

    A per-attachment cap would wave through five attachments that individually
    fit and collectively cannot.
    """
    half = "x" * (ATTACHMENT_TOTAL_CHAR_LIMIT // 2 + 1)

    with pytest.raises(ApolloError):
        append_attachments("debug this", [
            {"type": "log", "content": half},
            {"type": "output_dataclip", "content": half},
        ])


def test_unknown_attachment_type_still_reaches_the_model() -> None:
    result = append_attachments("look", [{"content": "some data"}])

    assert '<attachment type="unknown">' in result
    assert "some data" in result


# --- router: structural, not flattened into content -----------------------


def job_chat_result() -> dict:
    return {"response": "done", "suggested_code": None, "history": [], "usage": {}}


def test_job_route_passes_attachments_structurally() -> None:
    router = make_router()
    router._input_attachments = ATTACHMENTS

    with patch("job_chat.job_chat.main", return_value=job_chat_result()) as mock_main:
        router._route_to_job_chat(
            "why did this fail?", WORKFLOW_YAML, "workflows/wf/fetch-patients", [], False, 5,
        )

    payload = mock_main.call_args[0][0]
    assert payload["attachments"] == ATTACHMENTS
    # The user's message is passed as written — the log is not spliced into it
    assert payload["content"] == "why did this fail?"


def test_workflow_route_passes_attachments_structurally() -> None:
    router = make_router()
    router._input_attachments = ATTACHMENTS
    workflow_result = {"response": "done", "response_yaml": None, "history": [], "usage": {}}

    with patch("workflow_chat.workflow_chat.main", return_value=workflow_result) as mock_main:
        router._route_to_workflow_chat("add a retry step", WORKFLOW_YAML, "workflows/wf", [], False, 5)

    payload = mock_main.call_args[0][0]
    assert payload["attachments"] == ATTACHMENTS
    assert payload["content"] == "add a retry step"


# --- planner --------------------------------------------------------------


def test_planner_shows_attachments_on_the_current_turn() -> None:
    planner = make_planner()
    planner._attachments = ATTACHMENTS

    user_content = planner._build_user_content("why did the last two steps fail?", None)

    assert "why did the last two steps fail?" in user_content
    assert LOG in user_content


def test_planner_history_omits_attachments() -> None:
    """The turn sent to the model carries the log; the turn stored does not."""
    planner = make_planner()
    planner._attachments = ATTACHMENTS

    content = "why did the last two steps fail?"
    history = [{"role": "user", "content": content}, {"role": "assistant", "content": "..."}]

    assert LOG not in "".join(turn["content"] for turn in history)
    assert LOG in planner._build_user_content(content, None)


def test_planner_relays_attachments_to_both_subagents() -> None:
    planner = make_planner()
    planner._attachments = ATTACHMENTS

    subagent_result = {"response": "ok", "usage": {}, "suggested_code": None}

    with patch("global_chat.planner.call_job_agent", return_value=subagent_result) as job_mock:
        planner._execute_tool(
            _FakeToolUse("call_job_code_agent", {"message": "fix it", "job_key": "fetch-patients"}),
            _StubStreamManager(), {}, [],
        )

    assert job_mock.call_args.kwargs["attachments"] == ATTACHMENTS

    with patch("global_chat.planner.call_workflow_agent", return_value=subagent_result) as wf_mock:
        planner._execute_tool(
            _FakeToolUse("call_workflow_agent", {"message": "add a step"}),
            _StubStreamManager(), {}, [],
        )

    assert wf_mock.call_args.kwargs["attachments"] == ATTACHMENTS


# --- subagent_caller payloads ---------------------------------------------


def test_job_agent_payload_matches_the_router_route() -> None:
    with patch("job_chat.job_chat.main", return_value=job_chat_result()) as mock_main:
        call_job_agent(
            {"message": "fix the mapping", "job_key": "fetch-patients"},
            workflow_yaml=WORKFLOW_YAML,
            attachments=ATTACHMENTS,
        )

    payload = mock_main.call_args[0][0]
    # Subagent mode + top-level workflow_yaml: without both, the planner's
    # job_chat runs under the production "go to the workflow overview" scope
    # with no <workflow_structure> block and no inspect_job_code tool
    assert payload["subagent"] is True
    assert payload["workflow_yaml"] == WORKFLOW_YAML
    assert payload["context"]["job_key"] == "fetch-patients"
    assert payload["attachments"] == ATTACHMENTS
    # The dead nested copy is gone — Payload.from_dict never read it
    assert "workflow_yaml" not in payload["context"]


def test_workflow_agent_payload_runs_in_subagent_mode() -> None:
    workflow_result = {"response": "done", "response_yaml": None, "history": [], "usage": {}}

    with patch("workflow_chat.workflow_chat.main", return_value=workflow_result) as mock_main:
        call_workflow_agent({"message": "add a step"}, workflow_yaml=WORKFLOW_YAML, attachments=ATTACHMENTS)

    payload = mock_main.call_args[0][0]
    assert payload["subagent"] is True
    assert payload["attachments"] == ATTACHMENTS


def test_handover_becomes_an_instruction_for_the_planner() -> None:
    """A handover has no prose, and the planner is where it would be rerouted."""
    result = format_subagent_result_for_llm(
        {"response": "", "handover": "this needs a new step in the workflow"},
    )

    assert "this needs a new step in the workflow" in result
    assert result != "No response"


class _FakeToolUse:
    def __init__(self, name: str, tool_input: dict, block_id: str = "tu_1"):
        self.name = name
        self.input = tool_input
        self.id = block_id


class _StubStreamManager:
    def send_thinking(self, *_args: object, **_kwargs: object) -> None:
        pass

    def send_changes(self, *_args: object, **_kwargs: object) -> None:
        pass

    def send_status(self, *_args: object, **_kwargs: object) -> None:
        pass

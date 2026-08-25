"""Unit tests for input-attachment passthrough.

Attachments must reach a subagent as the exact bytes the user sent (never the
planner's paraphrase), and must never end up in the history that is returned to
the client and replayed on later turns.

job_chat already had typed context fields for this content, so attachments are
mapped onto those rather than given a second channel. workflow_chat and the
planner have no such fields, so they get a rendered block.
"""

from unittest.mock import patch

import pytest
from global_chat.subagent_caller import (
    call_job_agent,
    call_workflow_agent,
    format_subagent_result_for_llm,
)
from util import (
    ATTACHMENT_TOTAL_CHAR_LIMIT,
    ApolloError,
    attachment_text,
    attachments_to_context,
    format_attachments,
    select_attachments,
)

from .test_planner import WORKFLOW_YAML, make_planner
from .test_router import make_router

LOG = "[JOB] ✗ Request failed with status 401 Unauthorized\n[R/T] Job exited with error code 1"
INPUT = '{"patients": []}'

ATTACHMENTS = [
    {"type": "log", "content": LOG},
    {"type": "input_dataclip", "content": INPUT},
]


# --- mapping onto job_chat's existing context fields -----------------------


def test_types_map_onto_the_fields_job_chat_already_renders() -> None:
    context = attachments_to_context([
        {"type": "log", "content": LOG},
        {"type": "input_dataclip", "content": INPUT},
        {"type": "output_dataclip", "content": "out"},
    ])

    assert context == {"log": LOG, "input": INPUT, "output": "out"}


def test_two_attachments_sharing_a_field_are_joined_not_overwritten() -> None:
    """input_dataclip and run_input both describe input; neither may be lost."""
    context = attachments_to_context([
        {"type": "input_dataclip", "content": "step input"},
        {"type": "run_input", "content": "run input"},
    ])

    assert "step input" in context["input"]
    assert "run input" in context["input"]


def test_unknown_type_is_reported_not_silently_dropped() -> None:
    with patch("util.create_logger") as mock_logger:
        context = attachments_to_context([{"type": "screenshot", "content": "..."}])

    assert context == {}
    mock_logger.return_value.warning.assert_called_once()


def test_no_attachments_maps_to_nothing() -> None:
    assert attachments_to_context(None) == {}
    assert attachments_to_context([]) == {}
    assert attachments_to_context([{"type": "log", "content": "  "}]) == {}


# --- typed content --------------------------------------------------------
#
# Content may arrive as a list of log lines or a dataclip object rather than a
# string. str() would render Python repr, which flattens a log onto one line.


def test_a_log_sent_as_lines_keeps_its_lines() -> None:
    assert attachment_text(["[R/T] started", "[JOB] failed"]) == "[R/T] started\n[JOB] failed"


def test_a_dataclip_sent_as_an_object_renders_as_json() -> None:
    rendered = attachment_text({"active": True, "ref": None})

    assert '"active": true' in rendered
    assert '"ref": null' in rendered


def test_a_string_is_left_exactly_as_it_arrived() -> None:
    assert attachment_text("[R/T] started\n[JOB] failed") == "[R/T] started\n[JOB] failed"


def test_typed_content_reaches_job_chat_readable() -> None:
    context = attachments_to_context([{"type": "log", "content": ["line one", "line two"]}])

    assert context["log"] == "line one\nline two"


# --- rendering for agents with no context fields --------------------------


def test_rendered_block_reproduces_content_verbatim() -> None:
    block = format_attachments(ATTACHMENTS)

    assert LOG in block
    assert '<attachment type="log">' in block
    assert '<attachment type="input_dataclip">' in block


def test_nothing_to_render_returns_empty_string() -> None:
    assert format_attachments(None) == ""
    assert format_attachments([]) == ""
    assert format_attachments([{"type": "log", "content": "  "}]) == ""


# --- the size guard -------------------------------------------------------


def test_a_large_attachment_that_fits_is_passed_whole() -> None:
    body = "HEAD" + ("x" * (ATTACHMENT_TOTAL_CHAR_LIMIT - 100)) + "TAIL"

    # Nothing is trimmed to make room — a log the user attached is read in full
    assert body in format_attachments([{"type": "log", "content": body}])
    assert attachments_to_context([{"type": "log", "content": body}])["log"] == body


def test_oversized_attachments_are_rejected_not_edited() -> None:
    body = "x" * (ATTACHMENT_TOTAL_CHAR_LIMIT + 1)

    with pytest.raises(ApolloError) as excinfo:
        format_attachments([{"type": "log", "content": body}])

    error = excinfo.value
    assert error.code == 400
    assert error.type == "ATTACHMENT_TOO_LARGE"
    # The message must name the offender, and must not carry its content
    assert "log" in error.message
    assert error.details["largest_attachment"]["characters"] == len(body)
    assert body not in error.message


def test_the_limit_applies_to_the_total_not_each_attachment() -> None:
    """The prompt carries them together, so the sum is the constraint."""
    half = "x" * (ATTACHMENT_TOTAL_CHAR_LIMIT // 2 + 1)

    with pytest.raises(ApolloError):
        attachments_to_context([
            {"type": "log", "content": half},
            {"type": "output_dataclip", "content": half},
        ])


# --- router: structural, not flattened into the message -------------------


def job_chat_result() -> dict:
    return {"response": "done", "suggested_code": None, "history": [], "usage": {}}


def test_job_route_passes_attachments_as_context() -> None:
    router = make_router()
    router._input_attachments = ATTACHMENTS

    with patch("job_chat.job_chat.main", return_value=job_chat_result()) as mock_main:
        router._route_to_job_chat(
            "why did this fail?", WORKFLOW_YAML, "workflows/wf/fetch-patients", [], False, 5,
        )

    payload = mock_main.call_args[0][0]
    assert payload["context"]["log"] == LOG
    assert payload["context"]["input"] == INPUT
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


def test_planner_shows_attachments_on_the_current_turn_only() -> None:
    planner = make_planner()
    planner._attachments = ATTACHMENTS

    content = "why did the last two steps fail?"
    user_content = planner._build_user_content(content, None)

    assert content in user_content
    assert LOG in user_content
    # run() records the raw content in the returned history, so the log cannot
    # be replayed as the current run on a later turn
    assert LOG not in content


def test_planner_offers_every_attachment_to_the_caller() -> None:
    """The planner hands the whole set down; the caller keeps what was named."""
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


def test_selection_keeps_only_what_was_named() -> None:
    assert select_attachments(ATTACHMENTS, ["log"]) == [ATTACHMENTS[0]]
    assert select_attachments(ATTACHMENTS, ["log", "input_dataclip"]) == ATTACHMENTS


def test_naming_nothing_forwards_nothing() -> None:
    """A subagent sees only what it is handed — there is no implicit default."""
    assert select_attachments(ATTACHMENTS, []) == []
    assert select_attachments(ATTACHMENTS, None) == []


# --- subagent_caller payloads ---------------------------------------------


def test_job_agent_payload_matches_the_router_route() -> None:
    with patch("job_chat.job_chat.main", return_value=job_chat_result()) as mock_main:
        call_job_agent(
            {"message": "fix the mapping", "job_key": "fetch-patients", "attachments": ["log"]},
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
    assert payload["context"]["log"] == LOG
    # ...and only the log, because that is what this call asked for
    assert "input" not in payload["context"]
    # The dead nested copy is gone — Payload.from_dict never read it
    assert "workflow_yaml" not in payload["context"]


def test_workflow_agent_payload_runs_in_subagent_mode() -> None:
    workflow_result = {"response": "done", "response_yaml": None, "history": [], "usage": {}}

    with patch("workflow_chat.workflow_chat.main", return_value=workflow_result) as mock_main:
        call_workflow_agent(
            {"message": "add a step", "attachments": ["log"]},
            workflow_yaml=WORKFLOW_YAML,
            attachments=ATTACHMENTS,
        )

    payload = mock_main.call_args[0][0]
    assert payload["subagent"] is True
    assert payload["attachments"] == [ATTACHMENTS[0]]


def test_a_subagent_call_that_names_nothing_gets_nothing() -> None:
    """The planner read the log and is only relaying an instruction."""
    with patch("job_chat.job_chat.main", return_value=job_chat_result()) as mock_main:
        call_job_agent(
            {"message": "change state.patients to state.cases", "job_key": "fetch-patients",
             "attachments": []},
            workflow_yaml=WORKFLOW_YAML,
            attachments=ATTACHMENTS,
        )

    assert "log" not in mock_main.call_args[0][0]["context"]


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

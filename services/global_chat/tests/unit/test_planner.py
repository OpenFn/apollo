"""Unit tests for PlannerAgent tool execution and user-content building."""

from pathlib import Path
from unittest.mock import patch

import anthropic
import httpx
import pytest
import yaml
from anthropic import BadRequestError

from util import ApolloError


import global_chat.planner as planner_module
from global_chat.planner import (
    _FINAL_ROUND_NOTICE,
    _api_error_message,
    PlannerAgent,
    PlannerResult,
)
from global_chat.tools.tool_definitions import TOOL_DEFINITIONS, build_web_tools
from streaming_util import STATUS_SEARCHING_WEB

WORKFLOW_YAML = """\
name: wf
jobs:
  fetch-patients:
    name: Fetch Patients
    body: get('/patients');
  load-dhis2:
    name: Load to DHIS2
    body: '// Add operations here'
"""


def make_planner() -> PlannerAgent:
    """Build a PlannerAgent without config or an Anthropic client."""
    planner = PlannerAgent.__new__(PlannerAgent)
    planner.current_yaml = WORKFLOW_YAML
    planner.yaml_modified = False
    planner.subagent_results = []
    planner._segments = []
    planner._attachments = []
    planner.api_key = "test-key"
    planner._user = None
    planner._metrics_opt_in = None
    return planner


def empty_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


class FakeToolUse:
    type = "tool_use"

    def __init__(self, name: str, tool_input: dict, block_id: str = "tu_1"):
        self.name = name
        self.input = tool_input
        self.id = block_id


class StubStreamManager:
    def __init__(self) -> None:
        self.thinking: list = []
        self.statuses: list[dict] = []
        self.text: list[str] = []

    def send_thinking(self, status: object = None, *_args: object, **_kwargs: object) -> None:
        self.thinking.append(status)

    def send_changes(self, *_args: object, **_kwargs: object) -> None:
        pass

    def send_status(
        self,
        content: str,
        steps: list | None = None,
        summary: str | None = None,
    ) -> None:
        self.statuses.append(
            {"content": content, "steps": steps, "summary": summary},
        )

    def send_text(self, chunk: str) -> None:
        self.text.append(chunk)


class FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeUsage:
    input_tokens = 0
    output_tokens = 0
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class FakeServerToolUse:
    type = "server_tool_use"

    def __init__(self, name: str, tool_input: dict, block_id: str = "srvtu_1") -> None:
        self.name = name
        self.input = tool_input
        self.id = block_id


class FakeResponse:
    def __init__(self, stop_reason: str, content: list) -> None:
        self.stop_reason = stop_reason
        self.content = content
        self.usage = FakeUsage()


def make_run_planner(max_tool_calls: int = 10) -> PlannerAgent:
    """A planner wired for run(), with no config, client, or tools."""
    planner = make_planner()
    planner.model = "claude-test"
    planner.max_tokens = 1024
    planner.max_tool_calls = max_tool_calls
    planner.tools = []
    planner.web_tools = []
    planner.web_search_enabled = False
    planner.web_search_downgraded = False
    return planner


def run_with(planner: PlannerAgent, responses: list, content: str = "q") -> PlannerResult:
    """Drive planner.run() over a scripted list of API responses."""
    with patch.object(PlannerAgent, "_build_system_prompt", return_value=[]), \
         patch.object(PlannerAgent, "_call_api", side_effect=list(responses)):
        return planner.run(content, None, None, [], stream=False)


def test_inspect_job_code_accepts_multiple_keys() -> None:
    planner = make_planner()
    block = FakeToolUse("inspect_job_code", {"job_keys": ["fetch-patients", "missing-step"]})

    result = planner._execute_tool(block, StubStreamManager(), empty_usage(), [])

    assert "get('/patients');" in result
    assert "No code found for job 'missing-step'" in result


def test_job_agent_failure_returns_error_tool_result() -> None:
    planner = make_planner()
    blocks = [FakeToolUse("call_job_code_agent", {"message": "write code", "job_key": "fetch-patients"})]
    meta = []

    with patch("global_chat.planner.call_job_agent", side_effect=RuntimeError("boom")):
        results = planner._execute_job_code_tools_parallel(blocks, StubStreamManager(), empty_usage(), meta)

    assert results[0]["content"].startswith("ERROR: The job code agent failed: boom")
    assert meta[0]["error"] == "boom"


def test_workflow_agent_failure_returns_error_tool_result() -> None:
    planner = make_planner()
    block = FakeToolUse("call_workflow_agent", {"message": "add a step"})

    with patch("global_chat.planner.call_workflow_agent", side_effect=RuntimeError("boom")):
        result = planner._execute_tool(block, StubStreamManager(), empty_usage(), [])

    assert result.startswith("ERROR: The workflow agent failed: boom")
    assert planner.current_yaml == WORKFLOW_YAML
    assert planner.yaml_modified is False


def test_job_key_is_required_by_the_schema() -> None:
    """The runtime guard is the enforcement, but `required` is what stops the
    model omitting the key in the first place. Nothing else pins it."""
    from global_chat.tools.tool_definitions import CALL_JOB_CODE_AGENT_TOOL

    assert "job_key" in CALL_JOB_CODE_AGENT_TOOL["input_schema"]["required"]


def test_job_code_with_an_unknown_key_names_the_real_ones() -> None:
    """_execute_tool_blocks routes every job-code block here, single or not, so
    this is the path production takes."""
    planner = make_planner()
    blocks = [FakeToolUse("call_job_code_agent", {"message": "write code", "job_key": "fetch_the_patients"})]

    with patch("global_chat.planner.call_job_agent") as call_job_agent:
        results = planner._execute_job_code_tools_parallel(
            blocks, StubStreamManager(), empty_usage(), []
        )

    call_job_agent.assert_not_called()
    assert "not found in workflow YAML" in results[0]["content"]
    assert "fetch-patients, load-dhis2" in results[0]["content"]


def test_unparseable_workflow_yaml_does_not_crash_the_turn() -> None:
    """current_yaml is an unvalidated client payload. Anything that parses has
    to reach an error message, not an exception."""
    for yaml_str in ["the workflow could not be built", "- a\n- b", "jobs:\n  - one\n  - two", "jobs:\n  2024: {}"]:
        planner = make_planner()
        planner.current_yaml = yaml_str
        blocks = [FakeToolUse("call_job_code_agent", {"message": "write code", "job_key": "fetch-patients"})]

        with patch("global_chat.planner.call_job_agent") as call_job_agent:
            results = planner._execute_job_code_tools_parallel(blocks, StubStreamManager(), empty_usage(), [])

        call_job_agent.assert_not_called()
        assert results[0]["content"].startswith("ERROR:"), yaml_str


def test_job_code_without_a_key_never_runs_the_subagent() -> None:
    """Code written with nowhere to go is thrown away, and the user is told a
    change was made that was not. Refuse before spending the call."""
    planner = make_planner()
    blocks = [FakeToolUse("call_job_code_agent", {"message": "write code"})]  # no job_key

    with patch("global_chat.planner.call_job_agent") as call_job_agent:
        results = planner._execute_job_code_tools_parallel(
            blocks, StubStreamManager(), empty_usage(), []
        )

    call_job_agent.assert_not_called()
    result = results[0]["content"]
    assert result.startswith("ERROR: job_key is required")
    # Naming the keys is what lets the planner correct itself this turn.
    assert "fetch-patients" in result
    assert "load-dhis2" in result
    assert planner.current_yaml == WORKFLOW_YAML
    assert planner.yaml_modified is False


def test_workflow_agent_yaml_response_updates_structure_view() -> None:
    planner = make_planner()
    block = FakeToolUse("call_workflow_agent", {"message": "add a step"})
    new_yaml = WORKFLOW_YAML + "  new-step:\n    name: New Step\n    body: '// Add operations here'\n"
    subagent_result = {"response": "Added the step.", "response_yaml": new_yaml, "usage": empty_usage()}

    with patch("global_chat.planner.call_workflow_agent", return_value=subagent_result):
        result = planner._execute_tool(block, StubStreamManager(), empty_usage(), [])

    assert "Updated workflow structure:" in result
    assert "new-step" in result
    assert planner.current_yaml == new_yaml
    assert planner.yaml_modified is True


def test_workflow_agent_without_yaml_reports_no_change() -> None:
    planner = make_planner()
    block = FakeToolUse("call_workflow_agent", {"message": "add a step"})
    subagent_result = {"response": "Which DHIS2 instance?", "response_yaml": None, "usage": empty_usage()}

    with patch("global_chat.planner.call_workflow_agent", return_value=subagent_result):
        result = planner._execute_tool(block, StubStreamManager(), empty_usage(), [])

    assert "[No workflow changes were made — no YAML was produced.]" in result
    assert "Updated workflow structure:" not in result
    assert planner.current_yaml == WORKFLOW_YAML
    assert planner.yaml_modified is False


def test_parallel_job_agent_failure_keeps_sibling_results() -> None:
    planner = make_planner()
    blocks = [
        FakeToolUse("call_job_code_agent", {"message": "m", "job_key": "fetch-patients"}, block_id="tu_ok"),
        FakeToolUse("call_job_code_agent", {"message": "m", "job_key": "load-dhis2"}, block_id="tu_bad"),
    ]

    def fake_call_job_agent(tool_input: dict, *_args: object, **_kwargs: object) -> dict:
        if tool_input["job_key"] == "load-dhis2":
            raise RuntimeError("boom")
        return {"response": "done", "suggested_code": "newCode();", "usage": empty_usage()}

    with patch("global_chat.planner.call_job_agent", side_effect=fake_call_job_agent):
        results = planner._execute_job_code_tools_parallel(blocks, StubStreamManager(), empty_usage(), [])

    by_id = {r["tool_use_id"]: r["content"] for r in results}
    assert "stitched into the workflow" in by_id["tu_ok"]
    assert by_id["tu_bad"].startswith("ERROR: The job code agent failed: boom")
    assert "newCode();" in planner.current_yaml
    assert planner.yaml_modified is True


def test_tool_blocks_run_workflow_before_job_against_updated_yaml() -> None:
    """Workflow tools must run first and mutate the YAML before job tools run.

    The job below targets a step that only exists AFTER the workflow agent
    runs, so it can only be matched/stitched if it sees the updated YAML.
    """
    planner = make_planner()
    new_yaml = WORKFLOW_YAML + "  new-step:\n    name: New Step\n    body: '// Add operations here'\n"
    call_order = []

    def fake_call_workflow_agent(*_args: object, **_kwargs: object) -> dict:
        call_order.append("workflow")
        return {"response": "Added the step.", "response_yaml": new_yaml, "usage": empty_usage()}

    def fake_call_job_agent(_tool_input: dict, workflow_yaml: str, *_args: object, **_kwargs: object) -> dict:
        call_order.append("job")
        # Proves the job agent saw the post-workflow YAML, not the snapshot.
        assert "new-step" in workflow_yaml
        return {"response": "done", "suggested_code": "newCode();", "usage": empty_usage()}

    blocks = [
        FakeToolUse("call_job_code_agent", {"message": "m", "job_key": "new-step"}, block_id="tu_job"),
        FakeToolUse("call_workflow_agent", {"message": "add a step"}, block_id="tu_wf"),
    ]

    with patch("global_chat.planner.call_workflow_agent", side_effect=fake_call_workflow_agent), \
         patch("global_chat.planner.call_job_agent", side_effect=fake_call_job_agent):
        results = planner._execute_tool_blocks(blocks, StubStreamManager(), empty_usage(), [])

    assert call_order == ["workflow", "job"]
    by_id = {r["tool_use_id"]: r["content"] for r in results}
    assert "stitched into the workflow" in by_id["tu_job"]
    assert "newCode();" in planner.current_yaml


def test_pause_turn_keeps_the_text_from_before_the_pause() -> None:
    planner = make_run_planner()
    responses = [
        FakeResponse("pause_turn", [FakeTextBlock("Half an answer. ")]),
        FakeResponse("end_turn", [FakeTextBlock("The rest.")]),
    ]

    result = run_with(planner, responses)

    assert result.response == "Half an answer. The rest."
    assert result.history[-1]["content"] == "Half an answer. The rest."
    assert [s["content"] for s in result.response_segments] == ["Half an answer. ", "The rest."]


def test_paused_text_survives_the_max_tool_calls_exit_without_duplicating() -> None:
    """Exiting the loop while still paused should keep the head exactly once."""
    planner = make_run_planner(max_tool_calls=2)
    responses = [
        FakeResponse("pause_turn", [FakeTextBlock("A")]),
        FakeResponse("pause_turn", [FakeTextBlock("B")]),
    ]

    result = run_with(planner, responses)

    assert result.response == "AB"
    # Pause rounds spend the same budget as real tool calls, so the loop stops.
    assert result.meta["planner_iterations"] == planner.max_tool_calls


def test_a_real_tool_round_resets_the_paused_text_buffer() -> None:
    """Narration from before a tool call is not part of the final answer."""
    planner = make_run_planner()
    responses = [
        FakeResponse("pause_turn", [FakeTextBlock("Stale narration. ")]),
        FakeResponse("tool_use", [FakeToolUse("search_documentation", {"query": "dhis2"})]),
        FakeResponse("end_turn", [FakeTextBlock("The real answer.")]),
    ]

    with patch("global_chat.planner.search_documentation_tool", return_value="docs"):
        result = run_with(planner, responses)

    assert result.response == "The real answer."


def test_a_mixed_round_keeps_server_tool_blocks_in_history() -> None:
    """A round with both a web search and a local tool should not drop the search blocks."""
    planner = make_run_planner()
    search_block = FakeServerToolUse("web_search", {"query": "dhis2 tracker api"})
    responses = [
        FakeResponse("tool_use", [search_block, FakeToolUse("search_documentation", {"query": "x"})]),
        FakeResponse("end_turn", [FakeTextBlock("Done.")]),
    ]
    seen = []

    def record_and_reply(_system: object, messages: list, _stream: object, _manager: object) -> FakeResponse:
        seen.append(list(messages))
        return responses.pop(0)

    with patch.object(PlannerAgent, "_build_system_prompt", return_value=[]), \
         patch.object(PlannerAgent, "_call_api", side_effect=record_and_reply), \
         patch("global_chat.planner.search_documentation_tool", return_value="docs"):
        planner.run("q", None, None, [], stream=False)

    assistant_turn = seen[1][-2]
    assert assistant_turn["role"] == "assistant"
    assert search_block in assistant_turn["content"]


def test_user_content_names_the_step_being_viewed() -> None:
    planner = make_planner()

    user_content = planner._build_user_content("fix this step", "workflows/my-wf/fetch-patients")

    assert "currently viewing the step 'fetch-patients'" in user_content
    assert "Existing workflow structure" in user_content


def test_user_content_falls_back_to_page_for_non_step_pages() -> None:
    planner = make_planner()

    user_content = planner._build_user_content("rename the workflow", "workflows/my-wf/settings")

    assert "workflows/my-wf/settings" in user_content
    assert "currently viewing the step" not in user_content


def test_step_name_is_taken_from_the_workflow_verbatim() -> None:
    """The user named the step; title-casing it renames it in the prose."""
    planner = make_planner()

    assert planner._display_name_for_job("fetch-patients") == "Fetch Patients"
    assert planner._display_name_for_job("load-dhis2") == "Load to DHIS2"


def test_step_key_is_title_cased_only_as_a_fallback() -> None:
    """With no name in the YAML there is nothing to preserve, so format the key."""
    planner = make_planner()
    planner.current_yaml = None

    assert planner._display_name_for_job("fetch-patients") == "Fetch Patients"


def test_settled_status_reports_its_steps_as_data() -> None:
    planner = make_planner()
    stream = StubStreamManager()

    planner._send_settled(
        stream,
        'Wrote code for "Fetch Patients"',
        steps=[{"key": "fetch-patients", "name": "Fetch Patients"}],
        summary="Wrote code for 1 step",
    )

    # On the wire, so the client can attach detail without reading the prose
    assert stream.statuses == [
        {
            "content": 'Wrote code for "Fetch Patients"',
            "steps": [{"key": "fetch-patients", "name": "Fetch Patients"}],
            "summary": "Wrote code for 1 step",
        },
    ]
    # And in the transcript, so a reload has what the live stream had
    assert planner._segments == [
        {
            "type": "status",
            "content": 'Wrote code for "Fetch Patients"',
            "steps": [{"key": "fetch-patients", "name": "Fetch Patients"}],
            "summary": "Wrote code for 1 step",
        },
    ]


def test_settled_status_without_steps_records_only_the_sentence() -> None:
    planner = make_planner()
    stream = StubStreamManager()

    planner._send_settled(stream, "Edited workflow structure")

    assert planner._segments == [
        {"type": "status", "content": "Edited workflow structure"},
    ]


class FakeUsage:
    input_tokens = 0
    output_tokens = 0
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class FakeText:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeResponse:
    def __init__(self, stop_reason: str, content: list) -> None:
        self.stop_reason = stop_reason
        self.content = content
        self.usage = FakeUsage()


def notice_sent(messages: list) -> bool:
    """Did the wrap-up notice reach the model in this request?"""
    return any(
        isinstance(block, dict) and block.get("text") == _FINAL_ROUND_NOTICE
        for message in messages
        if isinstance(message["content"], list)
        for block in message["content"]
    )


def run_planner(max_tool_calls: int, tool_uses_per_round: int) -> tuple[list, list, str]:
    """Run the tool loop against a model that keeps calling tools.

    Returns, per API call, the tool_choice and whether the wrap-up notice was
    in the request, plus the final response.
    """
    planner = make_planner()
    planner.model = "test-model"
    planner.max_tool_calls = max_tool_calls
    tool_choices: list = []
    notices: list = []

    def fake_api(*_args: object, tool_choice: dict | None = None) -> FakeResponse:
        tool_choices.append(tool_choice)
        notices.append(notice_sent(_args[1]))
        if tool_choice is None:
            blocks = [
                FakeToolUse("inspect_job_code", {"job_keys": ["a"]}, f"tu_{i}")
                for i in range(tool_uses_per_round)
            ]
            return FakeResponse("tool_use", blocks)
        return FakeResponse("end_turn", [FakeText("Here is what changed.")])

    def fake_execute(blocks: list, *_args: object) -> list[dict]:
        return [{"type": "tool_result", "tool_use_id": b.id, "content": "ok"} for b in blocks]

    with patch.object(planner, "_call_api", side_effect=fake_api), \
         patch.object(planner, "_execute_tool_blocks", side_effect=fake_execute), \
         patch.object(planner, "_build_system_prompt", return_value="sys"):
        result = planner.run(
            content="x", workflow_yaml=None, page=None, history=[], stream=False,
        )

    return tool_choices, notices, result.response


def test_model_api_error_is_not_reported_as_a_tool_failure() -> None:
    """A prompt that outgrows the context window arrives as a 400 from the
    model API. Reporting it as a tool error hides the one failure the tool
    budget exists to prevent."""
    planner = make_planner()
    planner.model = "test-model"
    planner.max_tool_calls = 5

    # Shaped like a real rejection: the SDK's own str() is the dict repr,
    # and the readable sentence is in the parsed body.
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json={})
    api_error = anthropic.BadRequestError(
        "Error code: 400 - {'type': 'error', 'error': {...}}",
        response=response,
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "prompt is too long: 250000 tokens > 200000 maximum",
            },
        },
    )

    with (
        patch.object(planner, "_call_api", side_effect=api_error),
        patch.object(planner, "_build_system_prompt", return_value="sys"),
        pytest.raises(ApolloError) as raised,
    ):
        planner.run(
            content="x", workflow_yaml=None, page=None, history=[], stream=False,
        )

    # A 400 like job_chat's, because it describes what the caller sent and
    # they can act on it, and typed so an oversized workflow is legible in
    # Sentry rather than lost among every other bad request.
    assert raised.value.code == 400
    assert raised.value.type == "PROMPT_TOO_LONG"
    assert raised.value.details["upstream_status"] == response.status_code
    # A sentence written for the person reading it, telling them the one
    # thing they can do. The upstream text is kept for whoever debugs us.
    assert raised.value.message == (
        "This conversation is too long for the AI service to read. "
        "Start a new session to continue."
    )
    assert raised.value.details["upstream_message"] == (
        "prompt is too long: 250000 tokens > 200000 maximum"
    )


def _raise_from_planner(error: Exception) -> ApolloError:
    planner = make_planner()
    planner.model = "test-model"
    planner.max_tool_calls = 5
    with (
        patch.object(planner, "_call_api", side_effect=error),
        patch.object(planner, "_build_system_prompt", return_value="sys"),
        pytest.raises(ApolloError) as raised,
    ):
        planner.run(
            content="x", workflow_yaml=None, page=None, history=[], stream=False,
        )
    return raised.value


def test_a_rejected_key_does_not_describe_our_account_to_the_caller() -> None:
    """The upstream sentence for an auth failure is about our key, and every
    user of the instance would be shown it in chat."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.AuthenticationError(
            "Error code: 401 - {'type': 'error', 'error': {...}}",
            response=httpx.Response(401, request=request, json={}),
            body={
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "invalid x-api-key",
                },
            },
        ),
    )

    assert "x-api-key" not in error.message
    assert error.message == "The AI service is misconfigured on our side."
    assert error.details["upstream_message"] == "invalid x-api-key"
    # 500 rather than the upstream 401: our key failing is not the caller
    # failing to authenticate, and platform/src/auth reserves 401 for that.
    assert error.code == 500


def test_our_own_request_shape_being_wrong_is_not_blamed_on_the_caller() -> None:
    """The planner sends beta headers, thinking and context-management config
    and tool definitions the caller never touches. Anthropic rejects those
    with a 400, and answering the caller 400 would blame them for it."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.BadRequestError(
            "Error code: 400",
            response=httpx.Response(400, request=request, json={}),
            body={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": (
                        "Unexpected value(s) `context-management-2025-06-27` "
                        "for the `anthropic-beta` header"
                    ),
                },
            },
        ),
    )

    assert error.code == 502
    assert error.type == "MODEL_API_ERROR"
    # The upstream sentence names our beta header, which means nothing to a
    # user. It goes to details and to Sentry instead.
    assert "anthropic-beta" not in error.message
    assert "anthropic-beta" in error.details["upstream_message"]
    assert error.details["upstream_status"] == 400


def test_a_payload_over_the_size_limit_is_the_callers_to_act_on() -> None:
    """413 is the sibling of prompt-too-long: their workflow is too big, and a
    retry of the same payload can never succeed."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.RequestTooLargeError(
            "Error code: 413",
            response=httpx.Response(413, request=request, json={}),
            body={"type": "error", "error": {"type": "request_too_large",
                                             "message": "request body too large"}},
        ),
    )

    assert error.code == 413
    assert error.type == "REQUEST_TOO_LARGE"
    assert error.message == (
        "This workflow is too large for the AI service to read. "
        "Try again with a smaller workflow."
    )


def test_a_stream_that_dies_mid_reply_does_not_record_the_opening_200() -> None:
    """The SDK builds a mid-stream error from the response that opened the
    stream, which succeeded, so its status would read as a call that worked."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.APIStatusError(
            "Overloaded",
            response=httpx.Response(200, request=request, json={}),
            body={"type": "error", "error": {"type": "overloaded_error",
                                             "message": "Overloaded"}},
        ),
    )

    assert error.details["upstream_status"] is None
    assert error.code == 502


def test_a_mid_stream_failure_is_classified_by_what_the_body_says() -> None:
    """Every mid-stream failure is a bare APIStatusError carrying the 200 that
    opened the stream, whatever actually went wrong, so the class says nothing
    and the body's type is the only thing left. Global chat streams, so this
    is the common path, not the corner."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def mid_stream(kind: str, message: str) -> ApolloError:
        return _raise_from_planner(
            anthropic.APIStatusError(
                f"{{'type': 'error', 'error': {{'type': '{kind}'}}}}",
                response=httpx.Response(200, request=request, json={}),
                body={"type": "error",
                      "error": {"type": kind, "message": message}},
            ),
        )

    # A rate limit during generation still gives the caller something to wait
    # on. Before the body was read it was an untyped 502 with no retry_after.
    limited = mid_stream("rate_limit_error", "rate limited")
    assert limited.code == 429
    assert limited.type == "RATE_LIMIT"
    assert limited.details["retry_after"] == 60

    # Our own tool definitions being wrong must not reach the user's chat
    # just because the stream had already opened.
    ours = mid_stream(
        "invalid_request_error",
        "tools.0.custom.input_schema: Extra inputs are not permitted",
    )
    assert ours.code == 502
    assert "input_schema" not in ours.message
    assert "input_schema" in ours.details["upstream_message"]

    # And the conversation outgrowing the window is still the caller's to act
    # on, even though it arrived wearing a 200.
    overflow = mid_stream(
        "invalid_request_error", "prompt is too long: 1200032 tokens > 1000000 maximum",
    )
    assert overflow.code == 400
    assert overflow.type == "PROMPT_TOO_LONG"


def test_an_overload_with_no_readable_body_still_says_to_try_again() -> None:
    """A 529 is the response most likely to come back from an edge with an
    HTML body, and then there is no type to read. It is also the one kind
    whose advice differs, so falling back to the class matters here."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.OverloadedError(
            "Error code: 529",
            response=httpx.Response(529, request=request, text="<html>busy</html>"),
            body="<html>busy</html>",
        ),
    )

    assert error.code == 502
    assert error.message == "The AI service is busy. Please try again shortly."


def test_details_do_not_carry_key_shaped_values_off_the_server() -> None:
    """details is serialised to the caller (errors.ts toErrorPayload), so the
    upstream sentence leaves the server even though only message is rendered."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.BadRequestError(
            "Error code: 400",
            response=httpx.Response(400, request=request, json={}),
            body={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "rejected token sk-ant-api03-" + "a" * 95,
                },
            },
        ),
    )

    assert "sk-ant-api03-" + "a" * 95 not in error.details["upstream_message"]


def test_the_cause_of_a_connection_failure_is_masked_too() -> None:
    """A proxy error carries the proxy URL, which is where credentials get
    written, and details is serialised to the caller."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    dropped = httpx.ProxyError("proxy rejected")
    dropped.__cause__ = Exception("http://user:sk-ant-api03-" + "b" * 95 + "@proxy:8080")

    error = _raise_from_planner(dropped)

    assert "sk-ant-api03-" + "b" * 95 not in error.details["cause"]


def test_a_dropped_connection_keeps_the_text_httpx_wrote() -> None:
    """The SDK only wraps httpx around the initial send, so a stream that dies
    while the body is being read raises a raw httpx error with no status."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        httpx.ReadError("peer closed connection", request=request),
    )

    assert error.code == 503
    assert error.message == "Unable to reach the AI service. Please try again."
    assert error.details["upstream_message"] == "peer closed connection"
    assert error.details["upstream_status"] is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # Anthropic's own shape: the readable sentence
        (
            {"error": {"type": "invalid_request_error", "message": "prompt is too long"}},
            "prompt is too long",
        ),
        # An intermediary can put anything where the dict is expected. Raising
        # here would escape the handler that calls it.
        ({"error": "upstream rate limited"}, "upstream returned 502"),
        ({"error": ["nope"]}, "upstream returned 502"),
        ({"error": {}}, "upstream returned 502"),
        # An unparseable body leaves the SDK holding raw response text, which
        # must not reach a user's chat
        ("<html><body>502 Bad Gateway</body></html>", "upstream returned 502"),
        (None, "upstream returned 502"),
    ],
)
def test_api_error_message_never_leaks_or_raises(body: object, expected: str) -> None:
    class FakeError(Exception):
        status_code = 502

    error = FakeError("Error code: 502 - {'raw': 'repr'}")
    error.body = body

    assert _api_error_message(error) == expected


def test_api_error_message_without_a_status() -> None:
    """With no body and no status there is nothing true left to say, and the
    class name is not something to put in front of a user."""

    class FakeError(Exception):
        pass

    assert _api_error_message(FakeError("boom")) == "FakeError"


def test_api_error_message_never_names_a_success_status() -> None:
    """A mid-stream failure carries the 200 that opened the stream, so naming
    the status would tell a user their request failed with a success code."""

    class FakeError(Exception):
        status_code = 200
        body = "<html>502 Bad Gateway</html>"

    assert "200" not in _api_error_message(FakeError("boom"))


def test_a_rate_limit_keeps_the_retry_after_the_bridge_contract_pins() -> None:
    """platform/test/server.test.ts asserts RATE_LIMIT carries retry_after, and
    dropping it would leave a caller with nothing to wait on."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.RateLimitError(
            "Error code: 429",
            response=httpx.Response(
                429, request=request, json={}, headers={"retry-after": "30"},
            ),
            body={"type": "error", "error": {"type": "rate_limit_error",
                                             "message": "rate limited"}},
        ),
    )

    assert error.code == 429
    assert error.type == "RATE_LIMIT"
    assert error.details["retry_after"] == 30


def test_a_rate_limit_without_the_header_still_gives_something_to_wait_on() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = _raise_from_planner(
        anthropic.RateLimitError(
            "Error code: 429",
            response=httpx.Response(429, request=request, json={}),
            body={},
        ),
    )

    assert error.details["retry_after"] == 60


def test_a_broken_retry_after_header_does_not_raise_inside_the_handler() -> None:
    """isdigit is true for characters int() rejects, so a stray byte in the
    header would raise from inside the except block and arrive as the generic
    500 this whole change exists to remove. And the value is someone else's,
    so a caller told to wait a century would wait forever."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def rate_limited(header: bytes) -> ApolloError:
        return _raise_from_planner(
            anthropic.RateLimitError(
                "Error code: 429",
                response=httpx.Response(
                    429, request=request, json={},
                    headers=[(b"retry-after", header)],
                ),
                body={"type": "error", "error": {"type": "rate_limit_error",
                                                 "message": "rate limited"}},
            ),
        )

    # "\xb2" is superscript two: isdigit() is True, int() raises.
    assert rate_limited(b"\xb2").details["retry_after"] == 60
    # An HTTP date is legal here and is not a number of seconds.
    assert rate_limited(b"Wed, 21 Oct 2026 07:28:00 GMT").details["retry_after"] == 60
    assert rate_limited(b"99999").details["retry_after"] == 300
    # CPython will not convert a string of more than 4300 digits, and h11's
    # header budget lets one that long through.
    assert rate_limited(b"9" * 4301).details["retry_after"] == 60
    assert rate_limited(b"0").details["retry_after"] == 1
    assert rate_limited(b"30").details["retry_after"] == 30


def test_our_account_failing_is_not_reported_as_the_caller_failing() -> None:
    """A 403 from the model API means our org cannot use it. Passing it
    through would answer the caller with a verdict we reached about
    ourselves, which is what the 401 rule exists to prevent."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    for sdk_error in (
        anthropic.PermissionDeniedError(
            "Error code: 403",
            response=httpx.Response(403, request=request, json={}),
            body={"type": "error", "error": {"type": "permission_error",
                                             "message": "not allowed"}},
        ),
        anthropic.NotFoundError(
            "Error code: 404",
            response=httpx.Response(404, request=request, json={}),
            body={"type": "error", "error": {"type": "not_found_error",
                                             "message": "model: nope"}},
        ),
    ):
        error = _raise_from_planner(sdk_error)
        assert error.code == 502, type(sdk_error).__name__
        assert error.type == "MODEL_API_ERROR"


def test_connection_failure_is_not_reported_as_a_tool_failure() -> None:
    """APIConnectionError is not an APIStatusError, and a dropped connection
    on a long round is the likeliest way one dies."""
    planner = make_planner()
    planner.model = "test-model"
    planner.max_tool_calls = 5

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    api_error = anthropic.APIConnectionError(request=request)

    with (
        patch.object(planner, "_call_api", side_effect=api_error),
        patch.object(planner, "_build_system_prompt", return_value="sys"),
        pytest.raises(ApolloError) as raised,
    ):
        planner.run(
            content="x", workflow_yaml=None, page=None, history=[], stream=False,
        )

    # 503 like job_chat: reaching them failed, so nothing upstream judged
    # the request and there is something to retry.
    assert raised.value.code == 503
    assert raised.value.type == "CONNECTION_ERROR"
    assert raised.value.details["upstream_status"] is None


def test_stream_dropping_midway_is_not_reported_as_a_tool_failure() -> None:
    """The SDK wraps httpx errors around the initial send only. On a streaming
    request that returns at the headers, so a connection dropping during
    generation raises a raw httpx error, and streaming is what global chat
    uses."""
    planner = make_planner()
    planner.model = "test-model"
    planner.max_tool_calls = 5

    dropped = httpx.RemoteProtocolError(
        "peer closed connection without sending complete message body"
    )

    with (
        patch.object(planner, "_call_api", side_effect=dropped),
        patch.object(planner, "_build_system_prompt", return_value="sys"),
        pytest.raises(ApolloError) as raised,
    ):
        planner.run(
            content="x", workflow_yaml=None, page=None, history=[], stream=True,
        )

    assert raised.value.code == 503
    assert raised.value.type == "CONNECTION_ERROR"


def test_connection_error_keeps_the_sdk_wording() -> None:
    """APIConnectionError's message is the SDK's own constant, not upstream
    text, so it is worth more to a reader than the class name."""
    error = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )

    assert _api_error_message(error) == "Connection error."


def test_spent_budget_still_ends_on_an_answer() -> None:
    tool_choices, notices, response = run_planner(max_tool_calls=2, tool_uses_per_round=1)

    # Two rounds of tools, then one more with them switched off and the
    # model told to wrap up
    assert tool_choices == [None, None, {"type": "none"}]
    assert notices == [False, False, True]
    assert response == "Here is what changed."


def test_parallel_batch_overshooting_the_budget_still_ends_on_an_answer() -> None:
    # A batch can push the count past the budget in one go (5 calls, budget 3)
    tool_choices, notices, response = run_planner(max_tool_calls=3, tool_uses_per_round=5)

    assert tool_choices == [None, {"type": "none"}]
    assert notices == [False, True]
    assert response == "Here is what changed."


class StubConfigLoader:
    """Minimal ConfigLoader stand-in."""

    def __init__(self, config: dict) -> None:
        self.config = config


class StubPromptLoader:
    """ConfigLoader stand-in for _build_system_prompt, which only calls get_prompt."""

    def __init__(self, **prompts: str) -> None:
        self._prompts = prompts

    def get_prompt(self, key: str) -> str:
        return self._prompts.get(key, "")


WEB_CONFIG = {
    "planner": {
        "model": "claude-opus",
        "web_search": {
            "max_uses": 5,
            "max_content_tokens": 10000,
            "allowed_domains": ["docs.dhis2.org"],
        },
    },
}


def build_planner(config: dict, *, web_search: bool) -> PlannerAgent:
    """Construct a real PlannerAgent with the Anthropic client stubbed out."""
    with patch("global_chat.planner.Anthropic"):
        return PlannerAgent(StubConfigLoader(config), api_key="test-key", web_search=web_search)


def test_web_tools_are_off_unless_the_request_asks_for_them() -> None:
    planner = build_planner(WEB_CONFIG, web_search=False)

    assert planner.web_tools == []
    assert planner.web_search_enabled is False
    assert planner.tools == TOOL_DEFINITIONS


def test_web_tools_are_appended_after_the_existing_tools() -> None:
    planner = build_planner(WEB_CONFIG, web_search=True)

    assert planner.tools[: len(TOOL_DEFINITIONS)] == TOOL_DEFINITIONS
    assert [t["name"] for t in planner.tools[len(TOOL_DEFINITIONS):]] == ["web_search", "web_fetch"]
    assert planner.web_search_enabled is True


def test_the_module_level_tool_list_is_never_mutated() -> None:
    before = list(TOOL_DEFINITIONS)

    build_planner(WEB_CONFIG, web_search=True)

    assert before == TOOL_DEFINITIONS


def test_an_empty_allowlist_keeps_the_tools_off_even_when_requested() -> None:
    planner = build_planner({"planner": {"web_search": {"allowed_domains": []}}}, web_search=True)

    assert planner.web_tools == []
    assert planner.web_search_enabled is False


def test_system_prompt_is_a_single_cached_block_without_web_tools() -> None:
    planner = make_run_planner()
    planner.config_loader = StubPromptLoader(planner_system_prompt="BASE PROMPT")

    blocks = planner._build_system_prompt()

    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_system_prompt_appends_an_uncached_web_block_with_the_allowlist() -> None:
    planner = make_run_planner()
    planner.config_loader = StubPromptLoader(
        planner_system_prompt="BASE PROMPT",
        planner_web_tools_prompt="WEB ADDENDUM {domains}",
    )
    planner.web_tools = build_web_tools(WEB_CONFIG)

    blocks = planner._build_system_prompt()

    # Two blocks, and only the first is cached: the addendum must stay after
    # the breakpoint, outside the cache key.
    assert [("cache_control" in block) for block in blocks] == [True, False]
    assert blocks[0]["text"] == "BASE PROMPT"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "WEB ADDENDUM docs.dhis2.org"


def test_the_web_tools_prompt_key_exists_in_prompts_yaml() -> None:
    path = Path(planner_module.__file__).parent / "prompts.yaml"
    prompts = yaml.safe_load(path.read_text(encoding="utf-8"))["prompts"]

    assert "{domains}" in prompts["planner_web_tools_prompt"]


def test_no_web_block_is_appended_when_the_prompt_is_missing() -> None:
    """An empty text block would be rejected by the API, so drop it."""
    planner = make_run_planner()
    planner.config_loader = StubPromptLoader(planner_system_prompt="BASE PROMPT")
    planner.web_tools = build_web_tools(WEB_CONFIG)

    blocks = planner._build_system_prompt()

    assert len(blocks) == 1


class FakeEvent:
    def __init__(self, event_type: str, **fields: object) -> None:
        self.type = event_type
        for key, value in fields.items():
            setattr(self, key, value)


class FakeBlockRef:
    def __init__(self, block_type: str) -> None:
        self.type = block_type


class FakeStream:
    def __init__(self, events: list, final: FakeResponse) -> None:
        self._events = events
        self._final = final

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self) -> FakeResponse:
        return self._final


class FakeMessages:
    def __init__(self, stream: FakeStream) -> None:
        self._stream = stream

    def stream(self, **_kwargs: object) -> FakeStream:
        return self._stream


class FakeClient:
    def __init__(self, stream: FakeStream) -> None:
        self.messages = FakeMessages(stream)


def block_start(block_type: str) -> FakeEvent:
    return FakeEvent("content_block_start", content_block=FakeBlockRef(block_type))


def text_delta(text: str) -> FakeEvent:
    return FakeEvent("content_block_delta", delta=FakeEvent("text_delta", text=text))


def test_server_tool_activity_spins_then_settles_once_per_round() -> None:
    """Two server-tool uses in one round should result in one line."""
    planner = make_run_planner()
    final = FakeResponse("end_turn", [FakeTextBlock("Answer.")])
    events = [
        block_start("server_tool_use"),
        block_start("web_search_tool_result"),
        block_start("server_tool_use"),
        block_start("web_fetch_tool_result"),
        text_delta("Answer."),
    ]
    planner.client = FakeClient(FakeStream(events, final))
    manager = StubStreamManager()

    planner._call_api([], [], True, manager)

    assert manager.thinking == [STATUS_SEARCHING_WEB, STATUS_SEARCHING_WEB]
    assert manager.statuses == [
        {"content": "Searched the web", "steps": None, "summary": None},
    ]
    assert planner._segments == [{"type": "status", "content": "Searched the web"}]


def test_the_spinner_uses_the_shared_web_status_pool() -> None:
    planner = make_run_planner()
    planner.client = FakeClient(FakeStream([block_start("server_tool_use")], FakeResponse("end_turn", [])))
    manager = StubStreamManager()

    planner._call_api([], [], True, manager)

    assert manager.thinking == [STATUS_SEARCHING_WEB]


def test_text_deltas_still_stream_alongside_the_new_branches() -> None:
    planner = make_run_planner()
    final = FakeResponse("end_turn", [FakeTextBlock("Hi there")])
    planner.client = FakeClient(FakeStream([text_delta("Hi "), text_delta("there")], final))
    manager = StubStreamManager()

    planner._call_api([], [], True, manager)

    assert manager.text == ["Hi ", "there"]


class FakeSearchResult:
    """A successful web_search_tool_result: content is a list."""

    type = "web_search_tool_result"

    def __init__(self) -> None:
        self.content = [{"type": "web_search_result", "url": "https://docs.dhis2.org/a"}]


class FakeSearchError:
    """A failed web_search_tool_result: content is a bare object."""

    type = "web_search_tool_result"

    def __init__(self) -> None:
        self.content = {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}


def test_meta_counts_searches_and_fetch_hostnames() -> None:
    planner = make_run_planner()
    planner.web_search_enabled = True
    responses = [
        FakeResponse("end_turn", [
            FakeServerToolUse("web_search", {"query": "dhis2 tracker"}, block_id="s1"),
            FakeSearchResult(),
            FakeServerToolUse("web_fetch", {"url": "https://docs.dhis2.org/en/tracker.html?q=secret"}, block_id="f1"),
            FakeServerToolUse("web_fetch", {"url": "https://docs.dhis2.org/en/events.html"}, block_id="f2"),
            FakeTextBlock("Here is the shape."),
        ]),
    ]

    result = run_with(planner, responses)

    assert (result.meta["web_searches"], result.meta["web_fetches"]) == (1, 2)
    # Hostnames only, deduplicated, and the ?q=secret query string is dropped.
    assert result.meta["web_domains"] == ["docs.dhis2.org"]
    assert result.meta["web_search_downgraded"] is False


def test_meta_counting_survives_the_error_result_shape() -> None:
    """A failed search returns content as an object. Counting
    reads server_tool_use blocks and must not touch either shape."""
    planner = make_run_planner()
    planner.web_search_enabled = True
    responses = [
        FakeResponse("end_turn", [
            FakeServerToolUse("web_search", {"query": "dhis2"}, block_id="s1"),
            FakeSearchError(),
            FakeTextBlock("Could not find it."),
        ]),
    ]

    result = run_with(planner, responses)

    assert result.meta["web_searches"] == 1
    assert result.meta["web_fetches"] == 0
    assert result.meta["web_domains"] == []


def test_meta_sums_web_usage_across_rounds() -> None:
    """A paused search continues into a second round; counts must accumulate."""
    planner = make_run_planner()
    planner.web_search_enabled = True
    responses = [
        FakeResponse("pause_turn", [
            FakeServerToolUse("web_search", {"query": "dhis2"}, block_id="s1"),
            FakeServerToolUse("web_fetch", {"url": "https://docs.dhis2.org/a.html"}, block_id="f1"),
        ]),
        FakeResponse("end_turn", [
            FakeServerToolUse("web_fetch", {"url": "https://docs.dhis2.org/b.html"}, block_id="f2"),
            FakeServerToolUse("web_fetch", {"url": "https://docs.openfn.org/c.html"}, block_id="f3"),
            FakeTextBlock("Done."),
        ]),
    ]

    result = run_with(planner, responses)

    assert (result.meta["web_searches"], result.meta["web_fetches"]) == (1, 3)
    assert result.meta["web_domains"] == ["docs.dhis2.org", "docs.openfn.org"]


def test_meta_omits_the_web_fields_when_web_search_is_off() -> None:
    planner = make_run_planner()
    responses = [FakeResponse("end_turn", [FakeTextBlock("Plain answer.")])]

    result = run_with(planner, responses)

    assert "web_searches" not in result.meta
    assert "web_search_downgraded" not in result.meta


def make_bad_request(message: str = "web search is not enabled for this account") -> BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return BadRequestError(message, response=httpx.Response(400, request=request), body=None)


def test_a_bad_request_with_web_tools_retries_without_them() -> None:
    planner = make_run_planner()
    planner.web_tools = build_web_tools(WEB_CONFIG)
    planner.tools = TOOL_DEFINITIONS + planner.web_tools
    planner.web_search_enabled = True
    planner.config_loader = StubPromptLoader(planner_system_prompt="BASE PROMPT")
    tools_per_call = []

    def fail_then_answer(_system: object, _messages: object, _stream: object, _manager: object) -> FakeResponse:
        tools_per_call.append([t.get("name") for t in planner.tools])
        if len(tools_per_call) == 1:
            raise make_bad_request()
        return FakeResponse("end_turn", [FakeTextBlock("Answered without the web.")])

    with patch.object(PlannerAgent, "_call_api", side_effect=fail_then_answer):
        result = planner.run("q", None, None, [], stream=False)

    # Two calls, first with the web tools, the retry without.
    assert [("web_search" in names) for names in tools_per_call] == [True, False]
    assert result.response == "Answered without the web."
    assert result.meta["web_search_downgraded"] is True
    assert result.response_segments[0] == {
        "type": "status",
        "content": "Web search is unavailable for this account — answering without it",
    }


def test_the_downgrade_rebuilds_the_system_prompt_without_the_web_block() -> None:
    """Otherwise the prompt still advertises two tools that are no longer sent."""
    planner = make_run_planner()
    planner.web_tools = build_web_tools(WEB_CONFIG)
    planner.tools = TOOL_DEFINITIONS + planner.web_tools
    planner.web_search_enabled = True
    planner.config_loader = StubPromptLoader(
        planner_system_prompt="BASE PROMPT",
        planner_web_tools_prompt="WEB ADDENDUM {domains}",
    )
    systems = []

    def fail_then_answer(system: list, _messages: object, _stream: object, _manager: object) -> FakeResponse:
        systems.append([block["text"] for block in system])
        if len(systems) == 1:
            raise make_bad_request()
        return FakeResponse("end_turn", [FakeTextBlock("Answered without the web.")])

    with patch.object(PlannerAgent, "_call_api", side_effect=fail_then_answer):
        planner.run("q", None, None, [], stream=False)

    # The first call carries the addendum, and the retry should not.
    assert systems == [["BASE PROMPT", "WEB ADDENDUM docs.dhis2.org"], ["BASE PROMPT"]]


def test_a_bad_request_without_web_tools_is_not_retried() -> None:
    planner = make_run_planner()
    calls = []

    def always_fail(*_args: object) -> FakeResponse:
        calls.append(1)
        raise make_bad_request("prompt is too long")

    with patch.object(PlannerAgent, "_build_system_prompt", return_value=[]), \
         patch.object(PlannerAgent, "_call_api", side_effect=always_fail), \
         pytest.raises(ApolloError):
        planner.run("q", None, None, [], stream=False)

    assert calls == [1]


def test_an_unrelated_bad_request_is_not_blamed_on_web_search() -> None:
    """A 400 the web tools did not cause must not produce the web-search status."""
    planner = make_run_planner()
    planner.web_tools = build_web_tools(WEB_CONFIG)
    planner.tools = TOOL_DEFINITIONS + planner.web_tools
    planner.web_search_enabled = True
    planner.config_loader = StubPromptLoader(planner_system_prompt="BASE PROMPT")

    def always_fail(*_args: object) -> FakeResponse:
        raise make_bad_request("prompt is too long: 250000 tokens > 200000 maximum")

    with patch.object(PlannerAgent, "_call_api", side_effect=always_fail), \
         pytest.raises(ApolloError) as excinfo:
        planner.run("q", None, None, [], stream=False)

    # The retry failed too, so the web tools were not the cause. The user gets
    # the real error and nothing is recorded about web search.
    assert "prompt is too long" in excinfo.value.message
    assert planner._segments == []


def test_the_web_search_status_is_only_sent_once_the_retry_has_earned_it() -> None:
    planner = make_run_planner()
    planner.web_tools = build_web_tools(WEB_CONFIG)
    planner.tools = TOOL_DEFINITIONS + planner.web_tools
    planner.web_search_enabled = True
    planner.config_loader = StubPromptLoader(planner_system_prompt="BASE PROMPT")
    segments_at_each_call = []

    def fail_then_answer(*_args: object) -> FakeResponse:
        # Snapshot before the retry runs: nothing may have been claimed yet.
        segments_at_each_call.append(list(planner._segments))
        if len(segments_at_each_call) == 1:
            raise make_bad_request()
        return FakeResponse("end_turn", [FakeTextBlock("Answered without the web.")])

    with patch.object(PlannerAgent, "_call_api", side_effect=fail_then_answer):
        result = planner.run("q", None, None, [], stream=False)

    # Neither the first call nor the retry saw a status already recorded.
    assert segments_at_each_call == [[], []]
    assert result.response_segments[0]["type"] == "status"


def test_a_second_bad_request_surfaces_the_original_error() -> None:
    planner = make_run_planner()
    planner.web_tools = build_web_tools(WEB_CONFIG)
    planner.tools = TOOL_DEFINITIONS + planner.web_tools
    planner.web_search_enabled = True
    planner.config_loader = StubPromptLoader(planner_system_prompt="BASE PROMPT")
    errors = [make_bad_request("web search is not enabled"), make_bad_request("something else")]

    def always_fail(*_args: object) -> FakeResponse:
        raise errors.pop(0)

    with patch.object(PlannerAgent, "_call_api", side_effect=always_fail), \
         pytest.raises(ApolloError) as excinfo:
        planner.run("q", None, None, [], stream=False)

    assert errors == []
    assert "web search is not enabled" in excinfo.value.message
    assert "something else" not in excinfo.value.message
    # The retry failed, so nothing was claimed about web search.
    assert planner._segments == []

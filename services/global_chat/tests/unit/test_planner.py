"""Unit tests for PlannerAgent tool execution and user-content building."""

from unittest.mock import patch

from global_chat.planner import PlannerAgent, PlannerResult
from global_chat.tools.tool_definitions import TOOL_DEFINITIONS
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
        self.statuses: list[str] = []
        self.text: list[str] = []

    def send_thinking(self, status: object = None, *_args: object, **_kwargs: object) -> None:
        self.thinking.append(status)

    def send_changes(self, *_args: object, **_kwargs: object) -> None:
        pass

    def send_status(self, content: str = "", *_args: object, **_kwargs: object) -> None:
        self.statuses.append(content)

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
    block = FakeToolUse("call_job_code_agent", {"message": "write code", "job_key": "fetch-patients"})
    meta = []

    with patch("global_chat.planner.call_job_agent", side_effect=RuntimeError("boom")):
        result = planner._execute_tool(block, StubStreamManager(), empty_usage(), meta)

    assert result.startswith("ERROR: The job code agent failed: boom")
    assert meta[0]["error"] == "boom"


def test_workflow_agent_failure_returns_error_tool_result() -> None:
    planner = make_planner()
    block = FakeToolUse("call_workflow_agent", {"message": "add a step"})

    with patch("global_chat.planner.call_workflow_agent", side_effect=RuntimeError("boom")):
        result = planner._execute_tool(block, StubStreamManager(), empty_usage(), [])

    assert result.startswith("ERROR: The workflow agent failed: boom")
    assert planner.current_yaml == WORKFLOW_YAML
    assert planner.yaml_modified is False


def test_job_code_without_matched_key_is_reported_as_not_stitched() -> None:
    planner = make_planner()
    block = FakeToolUse("call_job_code_agent", {"message": "write code"})  # no job_key
    subagent_result = {"response": "done", "suggested_code": "newCode();", "usage": empty_usage()}

    with patch("global_chat.planner.call_job_agent", return_value=subagent_result):
        result = planner._execute_tool(block, StubStreamManager(), empty_usage(), [])

    assert "NOT added to the workflow" in result
    assert "stitched into the workflow" not in result
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


class StubConfigLoader:
    """Minimal ConfigLoader stand-in."""

    def __init__(self, config: dict) -> None:
        self.config = config


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
    assert manager.statuses == ["Searched the web"]
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

"""Unit tests for PlannerAgent tool execution and user-content building."""

from unittest.mock import patch

from global_chat.planner import PlannerAgent, PlannerResult
from global_chat.tools.tool_definitions import TOOL_DEFINITIONS

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
    def send_thinking(self, *_args: object, **_kwargs: object) -> None:
        pass

    def send_changes(self, *_args: object, **_kwargs: object) -> None:
        pass

    def send_status(self, *_args: object, **_kwargs: object) -> None:
        pass


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

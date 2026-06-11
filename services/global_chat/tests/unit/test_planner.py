"""Unit tests for PlannerAgent tool execution and user-content building."""

from unittest.mock import patch

from global_chat.planner import PlannerAgent

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
    def __init__(self, name: str, tool_input: dict, block_id: str = "tu_1"):
        self.name = name
        self.input = tool_input
        self.id = block_id


class StubStreamManager:
    def send_thinking(self, *_args: object, **_kwargs: object) -> None:
        pass


def test_inspect_job_code_accepts_multiple_keys() -> None:
    planner = make_planner()
    block = FakeToolUse("inspect_job_code", {"job_keys": ["fetch-patients", "missing-step"]})

    result = planner._execute_tool(block, empty_usage(), [])

    assert "get('/patients');" in result
    assert "No code found for job 'missing-step'" in result


def test_job_agent_failure_returns_error_tool_result() -> None:
    planner = make_planner()
    block = FakeToolUse("call_job_code_agent", {"message": "write code", "job_key": "fetch-patients"})
    meta = []

    with patch("global_chat.planner.call_job_agent", side_effect=RuntimeError("boom")):
        result = planner._execute_tool(block, empty_usage(), meta)

    assert result.startswith("ERROR: The job code agent failed: boom")
    assert meta[0]["error"] == "boom"


def test_workflow_agent_failure_returns_error_tool_result() -> None:
    planner = make_planner()
    block = FakeToolUse("call_workflow_agent", {"message": "add a step"})

    with patch("global_chat.planner.call_workflow_agent", side_effect=RuntimeError("boom")):
        result = planner._execute_tool(block, empty_usage(), [])

    assert result.startswith("ERROR: The workflow agent failed: boom")
    assert planner.current_yaml == WORKFLOW_YAML
    assert planner.yaml_modified is False


def test_job_code_without_matched_key_is_reported_as_not_stitched() -> None:
    planner = make_planner()
    block = FakeToolUse("call_job_code_agent", {"message": "write code"})  # no job_key
    subagent_result = {"response": "done", "suggested_code": "newCode();", "usage": empty_usage()}

    with patch("global_chat.planner.call_job_agent", return_value=subagent_result):
        result = planner._execute_tool(block, empty_usage(), [])

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
        result = planner._execute_tool(block, empty_usage(), [])

    assert "Updated workflow structure:" in result
    assert "new-step" in result
    assert planner.current_yaml == new_yaml
    assert planner.yaml_modified is True


def test_workflow_agent_without_yaml_reports_no_change() -> None:
    planner = make_planner()
    block = FakeToolUse("call_workflow_agent", {"message": "add a step"})
    subagent_result = {"response": "Which DHIS2 instance?", "response_yaml": None, "usage": empty_usage()}

    with patch("global_chat.planner.call_workflow_agent", return_value=subagent_result):
        result = planner._execute_tool(block, empty_usage(), [])

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

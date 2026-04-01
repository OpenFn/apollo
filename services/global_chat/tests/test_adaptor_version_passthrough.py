"""
Test that adaptor version strings are preserved through the planner chain:
workflow_agent returns YAML → planner stores it → planner calls job_code_agent
→ job_chat receives the correct adaptor with version intact.

Mocks both subagents and lets the planner LLM orchestrate them.
"""
import pytest
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")


WORKFLOW_YAML_WITH_VERSIONS = """\
name: test-workflow
jobs:
  fetch-submissions:
    name: Fetch KoboToolbox Submissions
    adaptor: '@openfn/language-kobotoolbox@4.2.11'
    body: '// Add operations here'
  upload-to-dhis2:
    name: Upload to DHIS2
    adaptor: '@openfn/language-dhis2@8.0.10'
    body: '// Add operations here'
triggers:
  webhook:
    type: webhook
    enabled: false
edges:
  webhook->fetch-submissions:
    source_trigger: webhook
    target_job: fetch-submissions
    condition_type: always
    enabled: true
  fetch-submissions->upload-to-dhis2:
    source_job: fetch-submissions
    target_job: upload-to-dhis2
    condition_type: on_job_success
    enabled: true
"""


@patch("global_chat.planner.call_job_agent")
@patch("global_chat.planner.call_workflow_agent")
def test_planner_passes_workflow_yaml_to_job_agent(mock_call_workflow, mock_call_job):
    """
    When the planner calls workflow_agent then job_code_agent, the YAML returned
    by workflow_agent (with adaptor versions) should be passed to call_job_agent
    with the version strings intact.
    """
    from global_chat.config_loader import ConfigLoader
    from global_chat.planner import PlannerAgent

    mock_call_workflow.return_value = {
        "response": "I've created a workflow with two steps.",
        "response_yaml": WORKFLOW_YAML_WITH_VERSIONS,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "_call_metadata": {"subagent": "workflow_agent"},
    }

    mock_call_job.return_value = {
        "response": "Here's the job code.",
        "suggested_code": "fetchSubmissions(state)",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "_call_metadata": {"subagent": "job_agent", "job_key": "fetch-submissions"},
    }

    config_loader = ConfigLoader()
    planner = PlannerAgent(config_loader=config_loader)

    result = planner.run(
        content="Create a workflow that fetches submissions from KoboToolbox and uploads to DHIS2, and write job code for both steps.",
        workflow_yaml=None,
        page=None,
        history=[],
        stream=False,
    )

    print(f"\nPlanner response: {result.response}")
    print(f"Tool calls: {[tc['tool'] for tc in result.meta.get('tool_calls', [])]}")
    print(f"args: {mock_call_job.call_args_list}")

    # Workflow agent must have been called
    assert mock_call_workflow.called, "Planner should have called workflow_agent"
    # Job agent must have been called at least once
    assert mock_call_job.called, "Planner should have called job_code_agent"

    # Every call_job_agent invocation should have received the workflow YAML
    # containing the versioned adaptors
    for job_call in mock_call_job.call_args_list:
        yaml_passed = job_call.kwargs.get("workflow_yaml") or job_call[1].get("workflow_yaml")
        assert yaml_passed is not None, "call_job_agent should receive workflow_yaml"
        assert "@openfn/language-kobotoolbox@4.2.11" in yaml_passed, (
            f"workflow_yaml passed to job_agent should contain versioned adaptor, got:\n{yaml_passed[:300]}"
        )
        assert "@openfn/language-dhis2@8.0.10" in yaml_passed, (
            f"workflow_yaml passed to job_agent should contain versioned adaptor, got:\n{yaml_passed[:300]}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

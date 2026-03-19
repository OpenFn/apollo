"""
Test that the planner correctly handles subagent "need more info" responses.

These tests mock the subagent calls to simulate scenarios where a subagent
asks for clarification, and verify the planner relays that back to the user.
"""
import pytest
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from global_chat.config_loader import ConfigLoader
from global_chat.planner import PlannerAgent


def make_workflow_agent_clarification_response(clarification_text: str) -> dict:
    """Build a mock workflow_agent response that asks for clarification (no YAML)."""
    return {
        "response": clarification_text,
        "response_yaml": "",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "_call_metadata": {"subagent": "workflow_agent"},
    }


@patch("global_chat.planner.call_workflow_agent")
def test_planner_relays_workflow_agent_clarification(mock_call_workflow):
    """
    When the workflow agent responds with a clarification question (no YAML),
    the planner should relay that question back to the user rather than
    inventing details or retrying silently.
    """
    clarification = (
        "I'd be happy to help create this workflow, but I need a bit more detail. "
        "You mentioned 'a database' — could you specify which database system you're "
        "using? For example, PostgreSQL, MySQL, MongoDB, or a cloud service like "
        "Google BigQuery? This will help me choose the right adaptor."
    )
    mock_call_workflow.return_value = make_workflow_agent_clarification_response(clarification)

    config_loader = ConfigLoader()
    planner = PlannerAgent(config_loader=config_loader)

    result = planner.run(
        content="I want to fetch my data from gmail and send it to my database",
        workflow_yaml=None,
        page=None,
        history=[],
        stream=False,
    )

    print(f"\n===== PLANNER RESPONSE =====")
    print(f"Response: {result.response}")
    print(f"Attachments: {result.attachments}")
    print(f"Tool calls: {result.meta.get('tool_calls', [])}")

    # The planner should have called the workflow agent
    assert mock_call_workflow.called, "Planner should have called workflow_agent"

    # The planner should NOT have produced a workflow YAML (since the subagent didn't)
    yaml_attachments = [a for a in result.attachments if a.get("type") == "workflow_yaml"]
    assert len(yaml_attachments) == 0, (
        f"Expected no workflow_yaml attachment since subagent asked for clarification, "
        f"but got: {yaml_attachments}"
    )

    # The planner's response should contain something about the database
    # (relaying the subagent's question or asking its own version)
    response_lower = result.response.lower()
    assert any(word in response_lower for word in ["database", "which", "specify", "clarif"]), (
        f"Expected planner to relay clarification about database, "
        f"got: {result.response[:200]}"
    )


@patch("global_chat.planner.call_workflow_agent")
def test_planner_does_not_retry_after_clarification(mock_call_workflow):
    """
    When the workflow agent asks for clarification, the planner should NOT
    call the workflow agent a second time with made-up details.
    """
    clarification = (
        "I need more information to create this workflow. What specific database "
        "are you using? For example: PostgreSQL, MySQL, MSSQL, or something else?"
    )
    mock_call_workflow.return_value = make_workflow_agent_clarification_response(clarification)

    config_loader = ConfigLoader()
    planner = PlannerAgent(config_loader=config_loader)

    result = planner.run(
        content="I want to fetch my data from gmail and send it to my database",
        workflow_yaml=None,
        page=None,
        history=[],
        stream=False,
    )

    print(f"\n===== PLANNER RESPONSE =====")
    print(f"Response: {result.response}")
    print(f"call_workflow_agent call count: {mock_call_workflow.call_count}")

    # The workflow agent should only have been called once — not retried
    assert mock_call_workflow.call_count == 1, (
        f"Expected workflow_agent to be called once, "
        f"but it was called {mock_call_workflow.call_count} times"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

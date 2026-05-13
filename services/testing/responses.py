"""Shared response helpers for acceptance tests.

Originally lived as duplicate code in `services/global_chat/tests/test_utils.py`
and the equivalent for other services. Centralised here so all acceptance tests
share one implementation.
"""

from typing import Any, Optional


def get_attachment(response: dict, attachment_type: str) -> Optional[str]:
    """Return the `content` of the first attachment matching `attachment_type`.

    Works for any service that returns `attachments: [{"type": ..., "content": ...}]`
    (today: global_chat). Returns None if no matching attachment.
    """
    for attachment in response.get("attachments", []) or []:
        if attachment.get("type") == attachment_type:
            return attachment.get("content")
    return None


def assert_routed_to(response: dict, expected_agent: str, *, context: str = "") -> None:
    """Assert `expected_agent` is present in `response["meta"]["agents"]`.

    `meta.agents` is a list like ["router", "planner"] or ["router", "workflow_agent"].
    Use this to verify the orchestrator routed the request the way you expected.
    """
    assert response is not None, f"{context}: response is None"
    assert isinstance(response, dict), f"{context}: response is not a dict ({type(response).__name__})"

    meta = response.get("meta") or {}
    agents = meta.get("agents") or []
    assert expected_agent in agents, (
        f"{context}: expected '{expected_agent}' in meta.agents, got {agents}"
    )


def assert_agent_calls(
    meta: dict,
    *,
    expected_agents: list[str],
    min_job_code_calls: int = 0,
    context: str = "",
) -> None:
    """Assert the planner orchestrated the expected sub-agents in the right order.

    Checks:
    - Every agent in `expected_agents` appears in `meta["agents"]`.
    - `meta["tool_calls"]` contains at least one `call_workflow_agent`.
    - `meta["tool_calls"]` contains at least `min_job_code_calls` of `call_job_code_agent`.
    - Every `call_job_code_agent` comes after the first `call_workflow_agent`.

    Used by global_chat planner-chain tests.
    """
    agents = meta.get("agents") or []
    for agent in expected_agents:
        assert agent in agents, f"{context}: expected '{agent}' in agents, got {agents}"

    tool_calls = meta.get("tool_calls") or []
    tool_names = [call.get("tool") for call in tool_calls]

    assert "call_workflow_agent" in tool_names, (
        f"{context}: expected call_workflow_agent in tool_calls, got {tool_names}"
    )

    job_code_indices = [i for i, name in enumerate(tool_names) if name == "call_job_code_agent"]
    assert len(job_code_indices) >= min_job_code_calls, (
        f"{context}: expected at least {min_job_code_calls} call_job_code_agent calls, "
        f"got {len(job_code_indices)}. Tool calls: {tool_names}"
    )

    workflow_idx = tool_names.index("call_workflow_agent")
    for j in job_code_indices:
        assert j > workflow_idx, (
            f"{context}: call_job_code_agent at index {j} came before "
            f"call_workflow_agent at index {workflow_idx}. Tool calls: {tool_names}"
        )


def latest_user_message(response: dict) -> Optional[dict]:
    """Return the most recent `role=user` message from `response["history"]`.

    Useful for verifying page-prefix tagging applied to the user's input.
    """
    history = response.get("history") or []
    for entry in reversed(history):
        if entry.get("role") == "user":
            return entry
    return None

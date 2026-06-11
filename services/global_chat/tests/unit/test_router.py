"""Unit tests for RouterAgent attachment building on the direct job_chat route."""

from unittest.mock import patch

from global_chat.router import RouterAgent

WORKFLOW_YAML = """\
name: wf
jobs:
  fetch-patients:
    name: Fetch Patients
    body: get('/patients');
"""


def make_router() -> RouterAgent:
    """Build a RouterAgent without config or an Anthropic client."""
    router = RouterAgent.__new__(RouterAgent)
    router.api_key = "test-key"
    router.routing_usage = {}
    router._input_attachments = []
    router._user = None
    router._metrics_opt_in = None
    return router


def job_chat_result(suggested_code: str | None) -> dict:
    return {"response": "done", "suggested_code": suggested_code, "history": [], "usage": {}}


def test_job_route_returns_only_full_yaml_attachment() -> None:
    router = make_router()

    with patch("job_chat.job_chat.main", return_value=job_chat_result("newCode();")):
        result = router._route_to_job_chat(
            "edit this", WORKFLOW_YAML, "workflows/wf/fetch-patients", [], False, 5,
        )

    assert [a["type"] for a in result.attachments] == ["workflow_yaml"]
    assert "newCode();" in result.attachments[0]["content"]


def test_job_route_with_unmatched_job_returns_no_attachments() -> None:
    router = make_router()

    with patch("job_chat.job_chat.main", return_value=job_chat_result("newCode();")):
        result = router._route_to_job_chat(
            "edit this", WORKFLOW_YAML, "workflows/wf/settings", [], False, 5, router_job_key="nonexistent",
        )

    assert result.attachments == []

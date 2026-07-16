"""Unit tests for RouterAgent attachment building on the direct job_chat route."""

from unittest.mock import patch

from global_chat.router import RouterAgent, RouterResult
from yaml_utils import workflow_has_job_code

EMPTY_YAML = """\
name: wf
jobs:
  fetch-patients:
    name: Fetch Patients
    body: '// Add operations here'
  send:
    name: Send
    body: '   '
"""

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
    router._stream_manager = None
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


def test_workflow_has_job_code_detects_real_code() -> None:
    assert workflow_has_job_code(WORKFLOW_YAML) is True


def test_workflow_has_job_code_treats_placeholder_and_blank_as_empty() -> None:
    assert workflow_has_job_code(EMPTY_YAML) is False


def test_workflow_has_job_code_handles_missing_or_unparseable_yaml() -> None:
    assert workflow_has_job_code(None) is False
    assert workflow_has_job_code("") is False
    assert workflow_has_job_code(": not valid yaml :") is False


def test_routing_message_tags_workflow_with_code() -> None:
    router = make_router()
    msg = router._build_routing_message("what does this do", WORKFLOW_YAML, None, [])
    assert "[Steps contain job code]" in msg


def test_routing_message_tags_empty_workflow() -> None:
    router = make_router()
    msg = router._build_routing_message("what does this do", EMPTY_YAML, None, [])
    assert "[All step bodies are empty/placeholder]" in msg


def test_job_route_sends_subagent_payload() -> None:
    router = make_router()

    with patch("job_chat.job_chat.main", return_value=job_chat_result(None)) as mock_main:
        router._route_to_job_chat(
            "explain this", WORKFLOW_YAML, "workflows/wf/fetch-patients", [], False, 5,
        )

    payload = mock_main.call_args[0][0]
    assert payload["subagent"] is True
    assert payload["workflow_yaml"] == WORKFLOW_YAML
    assert payload["context"]["job_key"] == "fetch-patients"


def make_planner_result() -> RouterResult:
    return RouterResult(
        response="planner answer",
        attachments=[],
        history=[],
        usage={"input_tokens": 10},
        meta={"agents": ["router", "planner"]},
    )


def test_job_route_handover_reroutes_to_planner() -> None:
    router = make_router()
    handed_over = {"response": "", "handover": "needs structure changes", "history": [], "usage": {"input_tokens": 7}}

    with patch("job_chat.job_chat.main", return_value=handed_over), \
         patch.object(RouterAgent, "_route_to_planner", return_value=make_planner_result()) as planner_mock:
        result = router._route_to_job_chat(
            "add a step", WORKFLOW_YAML, "workflows/wf/fetch-patients", [], False, 5,
        )

    planner_mock.assert_called_once()
    assert result.response == "planner answer"
    assert result.meta["handover_from"] == "job_code_agent"
    assert result.meta["handover_reason"] == "needs structure changes"
    # Usage from the aborted job_chat call is kept on top of the planner's
    assert result.usage["input_tokens"] == 17


def test_workflow_route_handover_reroutes_to_planner() -> None:
    router = make_router()
    handed_over = {
        "response": "", "response_yaml": None, "handover": "asks about job code",
        "history": [], "usage": {"input_tokens": 3},
    }

    with patch("workflow_chat.workflow_chat.main", return_value=handed_over), \
         patch.object(RouterAgent, "_route_to_planner", return_value=make_planner_result()) as planner_mock:
        result = router._route_to_workflow_chat(
            "what does this code do", WORKFLOW_YAML, "workflows/wf", [], False, 4,
        )

    planner_mock.assert_called_once()
    assert result.meta["handover_from"] == "workflow_agent"
    assert result.usage["input_tokens"] == 13

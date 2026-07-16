"""Integration tests for subagent handover: curated misroutes sent directly to
job_chat and workflow_chat, as if the router had picked the wrong destination.

These hit the live Anthropic API (manual/nightly, costs tokens). Each service
gets two scenarios: an obvious misroute, and an oblique one where the request
never names the other step — the model has to work out that what's being asked
lies beyond what it can see or edit.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from job_chat.job_chat import main as job_chat_main  # noqa: E402
from workflow_chat.workflow_chat import main as workflow_chat_main  # noqa: E402

pytestmark = pytest.mark.integration

WORKFLOW_YAML = """\
name: patient-sync
jobs:
  fetch-patients:
    id: 5f2f36e7-3f42-4b0a-9c11-9b3f5a3d1a01
    name: Fetch Patients
    adaptor: "@openfn/language-http@latest"
    body: |
      get('/patients');
  notify-admin:
    id: 8a1c22d0-6e4f-49d3-b6a2-4bfeb1f0c902
    name: Notify Admin
    adaptor: "@openfn/language-http@latest"
    body: |
      fn(state => {
        if (!state.data || state.data.length === 0) {
          console.warn('SYNC-WARN-042: no patient recrods found');
        }
        return state;
      });
triggers:
  webhook:
    id: 2d7f80b3-1c55-47a9-8e2f-6a90d24c7a03
    type: webhook
edges:
  webhook->fetch-patients:
    id: c4e9a1f6-0d82-4c37-9b54-7e315f68bd04
    source_trigger: webhook
    target_job: fetch-patients
    condition_type: always
"""


def job_chat_payload(content: str) -> dict:
    return {
        "content": content,
        "suggest_code": True,
        "subagent": True,
        "workflow_yaml": WORKFLOW_YAML,
        "context": {
            "expression": "get('/patients');",
            "adaptor": "@openfn/language-http@latest",
            "page_name": "Fetch Patients",
            "job_key": "fetch-patients",
        },
    }


def workflow_chat_payload(content: str) -> dict:
    return {
        "content": content,
        "subagent": True,
        "existing_yaml": WORKFLOW_YAML,
    }


def test_job_chat_hands_over_structural_request() -> None:
    """A workflow-structure request misrouted to job_chat must hand over,
    with no user-visible reply text and no code attached."""
    result = job_chat_main(job_chat_payload(
        "Add a new step after this one that sends the patients to Salesforce, and connect it up",
    ))

    assert result.get("handover")
    assert result["response"] == ""
    assert result.get("suggested_code") is None


def test_job_chat_hands_over_oblique_other_step_edit() -> None:
    """An edit whose target code lives in another step, described by what it
    does rather than by name, must hand over — not be bodged into the focused
    step or met with 'I can't see that code'."""
    result = job_chat_main(job_chat_payload(
        "The warning we log when no patients are found should include the run date too, can you update it?",
    ))

    assert result.get("handover")
    assert result["response"] == ""
    assert result.get("suggested_code") is None


def test_workflow_chat_hands_over_code_request() -> None:
    """A job-code request misrouted to workflow_chat must hand over,
    with no user-visible reply text and no YAML."""
    result = workflow_chat_main(workflow_chat_payload(
        "Why does the code in my fetch-patients step return an empty array? Can you fix it?",
    ))

    assert result.get("handover")
    assert result["response"] == ""
    assert not result.get("response_yaml")


def test_job_chat_hands_over_when_focused_step_is_wrong() -> None:
    """Right subagent, wrong step: the user says "this step" but the code they
    describe lives in a different step than the one the router focused. The
    model must not claim it can't see the warning, and must not bodge a new
    warning into the wrong step."""
    result = job_chat_main(job_chat_payload(
        "Fix the typo in the warning message this step logs when there are no patients",
    ))

    assert result.get("handover")
    assert result["response"] == ""
    assert result.get("suggested_code") is None


def test_workflow_chat_hands_over_oblique_code_change() -> None:
    """A code-level change described without naming any step must hand over —
    workflow_chat sees only redacted job bodies and cannot make it."""
    result = workflow_chat_main(workflow_chat_payload(
        "Can you change the wording of the warning we log when no patients come back?",
    ))

    assert result.get("handover")
    assert result["response"] == ""
    assert not result.get("response_yaml")

"""Unit tests for job_chat's subagent-mode system prompt."""

from job_chat.prompt import generate_system_message

WORKFLOW_YAML = """\
name: wf
jobs:
  fetch-patients:
    name: Fetch Patients
    body: get('/patients');
"""


def system_text(**kwargs) -> str:
    blocks = generate_system_message(context_dict={}, search_results=None, **kwargs)
    return "\n".join(b["text"] for b in blocks)


def test_production_prompt_keeps_navigate_instruction():
    text = system_text()

    # Production callers never set subagent: the only-job-code scope and the
    # go-to-the-workflow-overview instruction must stay untouched, and no
    # subagent sections appear
    assert "tell them to navigate to the workflow overview" in text
    assert "Do NOT help with overall workflow structure" in text
    assert "inspect_workflow" not in text
    assert "<workflow_structure>" not in text


def test_subagent_prompt_strips_navigate_instruction():
    text = system_text(subagent=True, workflow_yaml=WORKFLOW_YAML)

    # Neither the go-elsewhere phrasing nor the only-job-code scope may be in
    # context at all (production_scope_instructions is omitted from the
    # composed subagent_system_role)
    assert "navigate to the workflow overview" not in text
    assert "Do NOT help with overall workflow structure" not in text
    assert "ONLY help with job code" not in text
    assert "inspect_workflow" in text
    assert "<workflow_structure>" in text


def test_subagent_prompt_names_focused_step():
    text = system_text(subagent=True, workflow_yaml=WORKFLOW_YAML)
    assert "No step is focused" in text

    blocks = generate_system_message(
        context_dict={"job_key": "fetch-patients"}, search_results=None,
        subagent=True, workflow_yaml=WORKFLOW_YAML,
    )
    text = "\n".join(b["text"] for b in blocks)
    assert "'fetch-patients'" in text

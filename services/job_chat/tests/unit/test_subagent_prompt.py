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


def _subagent_text(context: dict) -> str:
    blocks = generate_system_message(
        context_dict=context, search_results=None,
        subagent=True, workflow_yaml=WORKFLOW_YAML,
    )
    return "\n".join(b["text"] for b in blocks)


def test_subagent_prompt_grounds_focus_in_viewed_step():
    # No viewing info: no focus sentence is emitted (the model works from
    # <user_code>), and no editing-plumbing phrasing leaks. Structure still shown.
    text = system_text(subagent=True, workflow_yaml=WORKFLOW_YAML)
    assert "<workflow_structure>" in text
    assert "No step is focused" not in text
    assert "loaded for editing" not in text
    assert "currently editing" not in text

    # Viewing the same step it can edit (common case): named and framed as open.
    text = _subagent_text({"job_key": "fetch-patients", "viewing": "Fetch Patients"})
    assert "Fetch Patients" in text
    assert "currently editing" in text

    # Viewing the workflow canvas: says "canvas" and still names the editable
    # step, with no editing-plumbing phrase.
    text = _subagent_text({"job_key": "fetch-patients", "viewing": "canvas"})
    assert "workflow canvas" in text
    assert "'fetch-patients'" in text
    assert "loaded for editing" not in text

    # Mismatch — viewing one step, editing another: states both, softly.
    text = _subagent_text({"job_key": "fetch-patients", "viewing": "Notify Admin"})
    assert "Notify Admin" in text
    assert "'fetch-patients'" in text
    assert "likely what their request is about" in text

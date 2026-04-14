"""
Routing matrix tests for global_chat.

Tests the core routing dimensions:
  - Information requests vs modification requests
  - Workflow view vs step editor view
  - Single-agent changes vs multi-agent changes

Each test uses the "Cat Poetry Competition" workflow fixture: a workflow with
generic step names (Fetch Data, Generate Text with Claude, Generate Text with
ChatGPT) whose bodies reveal it is actually a cat poetry competition producing
couplets in Swedish (Claude) and Estonian (ChatGPT).  This verifies that the
model inspects body keys, not just step names.
"""

import pytest
import yaml
from .test_utils import (
    call_global_chat_service,
    make_service_input,
    print_response_details,
    assert_routed_to,
    get_response_yaml,
    assert_yaml_equal_except,
    assert_yaml_jobs_have_body,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CAT_POETRY_COMPETITION_YAML = """\
name: text-generation-pipeline
jobs:
  fetch-data:
    id: job-fetch-id
    name: Fetch Data
    adaptor: '@openfn/language-http@latest'
    body: |
      get('https://catfact.ninja/fact');
      fn(state => {
        state.catFact = state.data.fact;
        return state;
      });
  generate-text-with-claude:
    id: job-claude-id
    name: Generate Text with Claude
    adaptor: '@openfn/language-http@latest'
    body: |
      post('https://api.anthropic.com/v1/messages', {
        body: {
          model: 'claude-sonnet-4-20250514',
          messages: [{
            role: 'user',
            content: `Write a couplet in Swedish about this cat fact for the cat poetry competition: ${state.catFact}`
          }]
        },
        headers: { 'x-api-key': state.configuration.anthropicKey }
      });
  generate-text-with-chatgpt:
    id: job-chatgpt-id
    name: Generate Text with ChatGPT
    adaptor: '@openfn/language-http@latest'
    body: |
      post('https://api.openai.com/v1/chat/completions', {
        body: {
          model: 'gpt-4',
          messages: [{
            role: 'user',
            content: `Write a couplet in Estonian about this cat fact for the cat poetry competition: ${state.catFact}`
          }]
        },
        headers: { Authorization: `Bearer ${state.configuration.openaiKey}` }
      });
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: true
edges:
  webhook->fetch-data:
    id: edge-1-id
    source_trigger: webhook
    target_job: fetch-data
    condition_type: always
    enabled: true
  fetch-data->generate-text-with-claude:
    id: edge-2-id
    source_job: fetch-data
    target_job: generate-text-with-claude
    condition_type: on_job_success
    enabled: true
  fetch-data->generate-text-with-chatgpt:
    id: edge-3-id
    source_job: fetch-data
    target_job: generate-text-with-chatgpt
    condition_type: on_job_success
    enabled: true
"""

CAT_POEM_YAML = """\
name: text-generation
jobs:
  generate-text:
    id: job-gen-id
    name: Generate Text
    adaptor: '@openfn/language-http@latest'
    body: |
      get('https://catfact.ninja/fact');
      fn(state => {
        state.catFact = state.data.fact;
        return state;
      });
      post('https://api.openai.com/v1/chat/completions', {
        body: {
          model: 'gpt-4',
          messages: [{
            role: 'user',
            content: `Write a short poem about this cat fact: ${state.catFact}`
          }]
        },
        headers: { Authorization: `Bearer ${state.configuration.openaiKey}` }
      });
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: true
edges:
  webhook->generate-text:
    id: edge-1-id
    source_trigger: webhook
    target_job: generate-text
    condition_type: always
    enabled: true
"""

WORKFLOW_PAGE = "workflows/text-generation-pipeline"
CLAUDE_STEP_PAGE = "workflows/text-generation-pipeline/generate-text-with-claude"
CHATGPT_STEP_PAGE = "workflows/text-generation-pipeline/generate-text-with-chatgpt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_routed_to_any(response, services, context=""):
    """Assert that the response was routed through at least one of the listed services."""
    meta = response.get("meta", {})
    agents = meta.get("agents", [])
    matched = [s for s in services if s in agents]
    assert len(matched) > 0, (
        f"{context}: Expected one of {services} in agents list, got {agents}"
    )


def get_job_body_from_response(response, job_key):
    """Extract a specific job's body from the workflow_yaml attachment."""
    yaml_str = get_response_yaml(response)
    if not yaml_str:
        return None
    try:
        data = yaml.safe_load(yaml_str)
        return data.get("jobs", {}).get(job_key, {}).get("body")
    except Exception:
        return None


def assert_planner_called_job_agent_times(response, min_calls, context=""):
    """Assert the planner invoked call_job_code_agent at least min_calls times."""
    meta = response.get("meta", {})
    tool_calls = meta.get("tool_calls", [])
    tool_names = [tc["tool"] for tc in tool_calls]
    job_code_count = tool_names.count("call_job_code_agent")
    assert job_code_count >= min_calls, (
        f"{context}: Expected at least {min_calls} call_job_code_agent calls, "
        f"got {job_code_count}. Tool calls: {tool_names}"
    )


# ---------------------------------------------------------------------------
# 1. Workflow Summary (information request, workflow view)
# ---------------------------------------------------------------------------

def test_workflow_summary():
    """
    Given the Cat Poetry Competition YAML with generic step names, ask
    'What does this do?' from the workflow view.

    The model must inspect body keys to discover the cat poetry theme,
    Swedish and Estonian languages. A vague description of 'text generation'
    is not sufficient.
    """
    print("==================TEST==================")
    print("Description: Verify the model reads body keys and describes "
          "the workflow as a cat poetry competition, not just 'text generation'.")

    service_input = make_service_input(
        existing_yaml=CAT_POETRY_COMPETITION_YAML,
        content="What does this do?",
        page=WORKFLOW_PAGE,
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_workflow_summary", content="What does this do?")

    assert response is not None
    assert "response" in response
    assert_routed_to_any(response, ["planner", "workflow_agent"],
                         context="test_workflow_summary")

    text = response["response"].lower()
    assert "cat" in text, (
        f"test_workflow_summary: Expected 'cat' in response (model should read body keys). "
        f"Response: {response['response'][:300]}"
    )
    assert "estonian" in text, (
        f"test_workflow_summary: Expected 'Estonian' in response. "
        f"Response: {response['response'][:300]}"
    )
    assert "swedish" in text, (
        f"test_workflow_summary: Expected 'Swedish' in response. "
        f"Response: {response['response'][:300]}"
    )


# ---------------------------------------------------------------------------
# 2. Step Summary from Workflow View (information request, workflow view)
# ---------------------------------------------------------------------------

def test_step_summary_from_workflow_view():
    """
    From the workflow view, ask 'What does the Claude step do?'

    Should describe the Claude prompt for a Swedish poem and ideally
    mention the cat poetry competition context.
    """
    print("==================TEST==================")
    print("Description: Ask about a specific step while on the workflow view.")

    service_input = make_service_input(
        existing_yaml=CAT_POETRY_COMPETITION_YAML,
        content="What does the Claude step do?",
        page=WORKFLOW_PAGE,
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_step_summary_from_workflow_view",
                           content="What does the Claude step do?")

    assert response is not None
    assert "response" in response
    assert_routed_to_any(response, ["job_code_agent", "planner"],
                         context="test_step_summary_from_workflow_view")

    text = response["response"].lower()
    assert "swedish" in text, (
        f"test_step_summary_from_workflow_view: Expected 'Swedish' mentioned. "
        f"Response: {response['response'][:300]}"
    )


# ---------------------------------------------------------------------------
# 3. Step Summary from Step Editor (information request, step editor view)
# ---------------------------------------------------------------------------

def test_step_summary_from_step_editor():
    """
    From the step editor (on the Claude step), ask 'What does this step do?'

    Same expectations as test 2 but routing may differ because the page URL
    points directly at the step.
    """
    print("==================TEST==================")
    print("Description: Ask about the current step while in the step editor.")

    service_input = make_service_input(
        existing_yaml=CAT_POETRY_COMPETITION_YAML,
        content="What does this step do?",
        page=CLAUDE_STEP_PAGE,
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_step_summary_from_step_editor",
                           content="What does this step do?")

    assert response is not None
    assert "response" in response
    assert_routed_to_any(response, ["job_code_agent", "planner"],
                         context="test_step_summary_from_step_editor")

    text = response["response"].lower()
    assert "swedish" in text, (
        f"test_step_summary_from_step_editor: Expected 'Swedish' mentioned. "
        f"Response: {response['response'][:300]}"
    )


# ---------------------------------------------------------------------------
# 4. Edit Single Step from Workflow View (modification, workflow view, one agent)
# ---------------------------------------------------------------------------

def test_edit_single_step_from_workflow():
    """
    From the workflow view, ask to modify the ChatGPT step to produce a haiku.

    The ChatGPT step body should contain 'haiku' and the rest of the YAML
    should be unchanged.
    """
    print("==================TEST==================")
    print("Description: Edit one step (ChatGPT -> haiku) from the workflow view.")

    service_input = make_service_input(
        existing_yaml=CAT_POETRY_COMPETITION_YAML,
        content="Modify ChatGPT step to ask for a haiku instead of a couplet.",
        page=WORKFLOW_PAGE,
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_edit_single_step_from_workflow",
                           content="Modify ChatGPT step to ask for a haiku instead of a couplet.")

    assert response is not None
    assert_routed_to_any(response, ["job_code_agent", "planner"],
                         context="test_edit_single_step_from_workflow")

    # ChatGPT body should now mention haiku
    chatgpt_body = get_job_body_from_response(response, "generate-text-with-chatgpt")
    assert chatgpt_body is not None, "Expected workflow_yaml attachment with chatgpt job body"
    assert "haiku" in chatgpt_body.lower(), (
        f"test_edit_single_step_from_workflow: Expected 'haiku' in ChatGPT body. "
        f"Body: {chatgpt_body[:300]}"
    )

    # Rest of YAML should be unchanged (allow chatgpt body to differ)
    yaml_str = get_response_yaml(response)
    orig = yaml.safe_load(CAT_POETRY_COMPETITION_YAML)
    parsed = yaml.safe_load(yaml_str)
    assert_yaml_equal_except(
        orig, parsed,
        allowed_paths=["jobs.generate-text-with-chatgpt.body"],
        context="test_edit_single_step_from_workflow: YAML changed outside ChatGPT body"
    )


# ---------------------------------------------------------------------------
# 5. Edit Single Step from Step Editor (modification, step editor view, one agent)
# ---------------------------------------------------------------------------

def test_edit_single_step_from_step_editor():
    """
    From the step editor on the ChatGPT step, ask to produce a haiku.

    Same expectations as test 4 but the page URL points to the ChatGPT step.
    """
    print("==================TEST==================")
    print("Description: Edit one step (ChatGPT -> haiku) from the step editor.")

    service_input = make_service_input(
        existing_yaml=CAT_POETRY_COMPETITION_YAML,
        content="Modify to ask for a haiku instead of a poem.",
        page=CHATGPT_STEP_PAGE,
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_edit_single_step_from_step_editor",
                           content="Modify to ask for a haiku instead of a poem.")

    assert response is not None
    assert_routed_to_any(response, ["job_code_agent", "planner"],
                         context="test_edit_single_step_from_step_editor")

    # ChatGPT body should now mention haiku
    chatgpt_body = get_job_body_from_response(response, "generate-text-with-chatgpt")
    assert chatgpt_body is not None, "Expected workflow_yaml attachment with chatgpt job body"
    assert "haiku" in chatgpt_body.lower(), (
        f"test_edit_single_step_from_step_editor: Expected 'haiku' in ChatGPT body. "
        f"Body: {chatgpt_body[:300]}"
    )

    # Rest of YAML should be unchanged
    yaml_str = get_response_yaml(response)
    orig = yaml.safe_load(CAT_POETRY_COMPETITION_YAML)
    parsed = yaml.safe_load(yaml_str)
    assert_yaml_equal_except(
        orig, parsed,
        allowed_paths=["jobs.generate-text-with-chatgpt.body"],
        context="test_edit_single_step_from_step_editor: YAML changed outside ChatGPT body"
    )


# ---------------------------------------------------------------------------
# 6. Edit Multiple Steps from Workflow View (modification, workflow view, multi-agent)
# ---------------------------------------------------------------------------

def test_edit_multiple_steps_from_workflow():
    """
    From the workflow view, ask to change all poems to French.

    Both generation step bodies should contain 'French' and neither should
    contain 'Swedish' or 'Estonian'. The planner should call job_code_agent
    at least twice.
    """
    print("==================TEST==================")
    print("Description: Edit two steps (all poems -> French) from the workflow view.")

    service_input = make_service_input(
        existing_yaml=CAT_POETRY_COMPETITION_YAML,
        content="I want all poems to be in French",
        page=WORKFLOW_PAGE,
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_edit_multiple_steps_from_workflow",
                           content="I want all poems to be in French")

    assert response is not None
    assert_routed_to(response, "planner", context="test_edit_multiple_steps_from_workflow")
    assert_planner_called_job_agent_times(response, 2,
                                          context="test_edit_multiple_steps_from_workflow")

    # Both generation steps should mention French
    claude_body = get_job_body_from_response(response, "generate-text-with-claude")
    chatgpt_body = get_job_body_from_response(response, "generate-text-with-chatgpt")

    assert claude_body is not None, "Expected Claude job body in response YAML"
    assert chatgpt_body is not None, "Expected ChatGPT job body in response YAML"

    assert "french" in claude_body.lower(), (
        f"test_edit_multiple_steps_from_workflow: Expected 'French' in Claude body. "
        f"Body: {claude_body[:300]}"
    )
    assert "french" in chatgpt_body.lower(), (
        f"test_edit_multiple_steps_from_workflow: Expected 'French' in ChatGPT body. "
        f"Body: {chatgpt_body[:300]}"
    )

    # Neither should still mention Swedish or Estonian
    assert "swedish" not in claude_body.lower(), (
        f"test_edit_multiple_steps_from_workflow: 'Swedish' should be removed from Claude body."
    )
    assert "estonian" not in chatgpt_body.lower(), (
        f"test_edit_multiple_steps_from_workflow: 'Estonian' should be removed from ChatGPT body."
    )

    # Structural parts of YAML should be unchanged
    yaml_str = get_response_yaml(response)
    orig = yaml.safe_load(CAT_POETRY_COMPETITION_YAML)
    parsed = yaml.safe_load(yaml_str)
    assert_yaml_equal_except(
        orig, parsed,
        allowed_paths=[
            "jobs.generate-text-with-claude.body",
            "jobs.generate-text-with-chatgpt.body",
        ],
        context="test_edit_multiple_steps_from_workflow: YAML changed outside generation bodies"
    )


# ---------------------------------------------------------------------------
# 7. Edit Multiple Steps from Step Editor (modification, step editor, multi-agent)
# ---------------------------------------------------------------------------

def test_edit_multiple_steps_from_step_editor():
    """
    From the step editor on the ChatGPT step, ask to change ALL poems in the
    cat poetry competition to French.

    The explicit mention of 'all poems' and 'cat poetry competition' should
    signal that both generation steps need updating, even though the user is
    on a single step page.
    """
    print("==================TEST==================")
    print("Description: Edit two steps (all poems -> French) from the step editor.")

    service_input = make_service_input(
        existing_yaml=CAT_POETRY_COMPETITION_YAML,
        content="I want all poems in the cat poetry competition to be in French",
        page=CHATGPT_STEP_PAGE,
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_edit_multiple_steps_from_step_editor",
                           content="I want all poems in the cat poetry competition to be in French")

    assert response is not None
    assert_routed_to(response, "planner", context="test_edit_multiple_steps_from_step_editor")
    assert_planner_called_job_agent_times(response, 2,
                                          context="test_edit_multiple_steps_from_step_editor")

    claude_body = get_job_body_from_response(response, "generate-text-with-claude")
    chatgpt_body = get_job_body_from_response(response, "generate-text-with-chatgpt")

    assert claude_body is not None, "Expected Claude job body in response YAML"
    assert chatgpt_body is not None, "Expected ChatGPT job body in response YAML"

    assert "french" in claude_body.lower(), (
        f"test_edit_multiple_steps_from_step_editor: Expected 'French' in Claude body. "
        f"Body: {claude_body[:300]}"
    )
    assert "french" in chatgpt_body.lower(), (
        f"test_edit_multiple_steps_from_step_editor: Expected 'French' in ChatGPT body. "
        f"Body: {chatgpt_body[:300]}"
    )

    assert "swedish" not in claude_body.lower(), (
        f"test_edit_multiple_steps_from_step_editor: 'Swedish' should be removed from Claude body."
    )
    assert "estonian" not in chatgpt_body.lower(), (
        f"test_edit_multiple_steps_from_step_editor: 'Estonian' should be removed from ChatGPT body."
    )


# ---------------------------------------------------------------------------
# 8. Add New Steps + Edit Workflow Structure (structural change, workflow view)
# ---------------------------------------------------------------------------

def test_add_steps_and_restructure():
    """
    Given a simple single-step 'Cat Poem' workflow, ask to turn it into a
    competition: send the cat fact to both Claude and ChatGPT, add a judge
    step, then send results.

    The output should have multiple jobs (at least 4: two generators, a
    judge, and a results step) with bodies populated.
    """
    print("==================TEST==================")
    print("Description: Restructure a single-step workflow into a multi-step "
          "poetry competition.")

    service_input = make_service_input(
        existing_yaml=CAT_POEM_YAML,
        content=(
            "Make this a poetry competition. Send it to both Claude and ChatGPT. "
            "Send that to another Claude step to be the judge. "
            "Then send me the results."
        ),
        page="workflows/text-generation",
        history=[],
    )
    response = call_global_chat_service(service_input)
    print_response_details(response, test_name="test_add_steps_and_restructure",
                           content="Make this a poetry competition...")

    assert response is not None
    assert_routed_to(response, "planner", context="test_add_steps_and_restructure")

    yaml_str = get_response_yaml(response)
    assert yaml_str is not None, "Expected a workflow_yaml attachment"

    parsed = yaml.safe_load(yaml_str)
    jobs = parsed.get("jobs", {})
    assert len(jobs) >= 4, (
        f"test_add_steps_and_restructure: Expected at least 4 jobs "
        f"(2 generators + judge + results), got {len(jobs)}: {list(jobs.keys())}"
    )

    assert_yaml_jobs_have_body(yaml_str, context="test_add_steps_and_restructure")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

"""User has just navigated from a job-code editor (where they were discussing
HTTP error handling) to a workflow editor and asks to add a new step. The
model should infer the context switch and respond about the workflow as a
structure, not continue talking about job-code error handling."""

import yaml

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import assert_no_special_chars


QUALITY_CRITERIA = [
    "The response talks about the workflow as a structure (jobs, edges, triggers), not about job-code-level error handling.",
    "The tone is warm and collaborative, not clinical or terse.",
    "If the response proposes a new email step, the rationale is plausible (e.g. mentions notification, summary, or alerting).",
]


EXISTING_YAML = """name: data-pipeline
jobs:
  fetch-source-data:
    id: job-fetch-id
    name: Fetch Source Data
    adaptor: '@openfn/language-http@6.5.4'
    body: 'get("https://source.api/data");'
  transform-data:
    id: job-transform-id
    name: Transform Data
    adaptor: '@openfn/language-common@latest'
    body: 'fn(state => { return { ...state, transformed: true }; });'
  save-to-database:
    id: job-save-id
    name: Save to Database
    adaptor: '@openfn/language-http@6.5.4'
    body: 'post("https://db.api/save", state => state.data);'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
edges:
  webhook->fetch-source-data:
    id: edge-webhook-fetch-id
    source_trigger: webhook
    target_job: fetch-source-data
    condition_type: always
    enabled: true
  fetch-source-data->transform-data:
    id: edge-fetch-transform-id
    source_job: fetch-source-data
    target_job: transform-data
    condition_type: on_job_success
    enabled: true
  transform-data->save-to-database:
    id: edge-transform-save-id
    source_job: transform-data
    target_job: save-to-database
    condition_type: on_job_success
    enabled: true
"""


def test_navigation_job_to_workflow(apollo_client):
    payload = build_workflow_chat_payload(
        existing_yaml=EXISTING_YAML,
        history=[
            {"role": "user", "content": "[pg:job_code/transform-data/http] Can you add error handling to this HTTP request?"},
            {"role": "assistant", "content": "I'll add try-catch error handling to catch any request failures in your HTTP job."},
            {"role": "user", "content": "[pg:job_code/transform-data/http] Also add retry logic with backoff"},
            {"role": "assistant", "content": "I'll add exponential backoff retry logic to handle transient failures."},
        ],
        user_message="Add a step to send the results via email",
        current_page="data-pipeline",
        previous_page={"type": "job_code", "name": "transform-data", "adaptor": "http"},
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response["response_yaml"], "Model should have generated YAML"

    yaml_obj = yaml.safe_load(response["response_yaml"])
    assert "jobs" in yaml_obj

    job_names = [job.get("name", "").lower() for job in yaml_obj["jobs"].values()]
    assert any("email" in n or "mail" in n or "send" in n for n in job_names), (
        f"Email job not found in workflow. Job names: {job_names}"
    )

    orig_yaml_obj = yaml.safe_load(EXISTING_YAML)
    assert len(yaml_obj["jobs"]) > len(orig_yaml_obj["jobs"]), (
        f"Expected a new job to be added. Original: {len(orig_yaml_obj['jobs'])}, "
        f"new: {len(yaml_obj['jobs'])}"
    )

    response_text = response["response"].lower()
    assert not any(phrase in response_text for phrase in ["try", "catch", "retry", "backoff", "error handling in the code"]), (
        "Response should be about workflow structure, not job-code error handling"
    )

    assert_no_special_chars(response["response_yaml"])

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(
        criteria=QUALITY_CRITERIA,
        candidate=response,
        test_notes=__doc__,
    )
    assert verdict.passed, verdict.summary

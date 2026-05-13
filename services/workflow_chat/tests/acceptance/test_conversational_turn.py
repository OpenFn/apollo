"""User asks a conversational question that should NOT lead to YAML changes.
The service should respond with text only, or with a YAML that is identical
to the existing one."""

import yaml

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import assert_no_special_chars


QUALITY_CRITERIA = [
    "The response engages conversationally with the user's request for clarification, without unnecessarily restructuring or rewriting the workflow.",
]


EXISTING_YAML = """
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    id: job-parse-id
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-common@latest'
    body: '| // Add data parsing and aggregation operations here'
  upload-to-redis:
    id: job-upload-id
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: '| // Add Redis collection upload operations here'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
edges:
  webhook->parse-and-aggregate-fridge-data:
    id: edge-webhook-parse-id
    source_trigger: webhook
    target_job: parse-and-aggregate-fridge-data
    condition_type: always
    enabled: true
  parse-and-aggregate-fridge-data->upload-to-redis:
    id: edge-parse-upload-id
    source_job: parse-and-aggregate-fridge-data
    target_job: upload-to-redis
    condition_type: on_job_success
    enabled: true
"""


def test_conversational_turn(apollo_client):
    payload = build_workflow_chat_payload(
        existing_yaml=EXISTING_YAML,
        history=[
            {
                "role": "user",
                "content": (
                    "Whenever fridge statistics are send to you, parse and aggregate "
                    "the data and upload to a collection in redis."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "I'll create a workflow that processes fridge statistics through a "
                    "webhook trigger, then aggregates and stores the data in Redis."
                ),
            },
        ],
        user_message="Can you explain that better",
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)

    response_yaml_str = response.get("response_yaml")
    if response_yaml_str and str(response_yaml_str).strip():
        orig_yaml = yaml.safe_load(EXISTING_YAML)
        response_yaml = yaml.safe_load(response_yaml_str)
        assert orig_yaml == response_yaml, "If YAML is present in response, it must be unchanged."
        assert_no_special_chars(response_yaml_str)

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary

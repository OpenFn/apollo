"""User asks workflow_chat to fill in job code, which is not its
responsibility. The service should politely explain that and avoid generating
or modifying actual job bodies. Any returned YAML should be unchanged from
the existing one (or absent)."""

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import assert_no_special_chars


QUALITY_CRITERIA = [
    "The response politely explains that filling in job code is not workflow_chat's responsibility, or otherwise declines the request gracefully.",
    "The response does not attempt to write actual job code into the workflow.",
]


EXISTING_YAML = """
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    id: job-parse-id
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-common@latest'
    body: 'print("hello a")'
  upload-to-redis:
    id: job-upload-id
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: 'print("hello a")'
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


def test_edit_job_code(apollo_client):
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
        user_message="Can you also fill in the job code for all the steps",
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)
    if response.get("response_yaml"):
        assert_no_special_chars(response["response_yaml"])

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary

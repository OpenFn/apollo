"""The service is invoked with an `errors` field (replacing `content`) — used
when the user's previous workflow attempt produced a validation error. The
service should acknowledge the error and produce a corrected workflow."""

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import assert_no_special_chars


QUALITY_CRITERIA = [
    "The response acknowledges the reported error rather than ignoring it.",
    "Any returned workflow YAML attempts to fix the cause of the error (in this case, an invalid adaptor).",
]


EXISTING_YAML = """
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    id: job-parse-id
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-commons@latest'
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


def test_error_field(apollo_client):
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
        errors="adaptor error",
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

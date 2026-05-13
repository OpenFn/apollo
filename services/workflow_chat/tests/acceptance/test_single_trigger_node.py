"""User asks for a change that implies multiple nodes coming directly from
the trigger. Only one node can come from the trigger in OpenFn — the service
should respect the constraint by picking one job to run first and branching
from there, not by adding multiple direct children of the trigger."""

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import assert_no_special_chars


QUALITY_CRITERIA = [
    "The proposed workflow respects the constraint that only one job can come directly from the trigger.",
    "If the user's request implies multiple parallel steps from the trigger, the response restructures it so one job runs first and the others branch off after.",
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
    body: 'print("hello b")'
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


def test_single_trigger_node(apollo_client):
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
        user_message="Actually I also want an email notification at the same time as the data is being parsed.",
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

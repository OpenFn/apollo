"""Second conversation turn requesting a change to the YAML. The service
should preserve every job from the original YAML while applying the requested
addition (data deduplication before validation)."""

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import (
    assert_no_special_chars,
    assert_yaml_section_contains_all,
)


QUALITY_CRITERIA = []  # mostly structural


EXISTING_YAML = """
name: CommCare-to-DHIS2-Patient-Integration
jobs:
  receive-commcare-data:
    id: job-receive-id
    name: Receive CommCare Patient Data
    adaptor: '@openfn/language-commcare@latest'
    body: 'PLACEHOLDER 1'
  validate-patient-data:
    id: job-validate-id
    name: Validate Patient Data
    adaptor: '@openfn/language-common@latest'
    body: 'PLACEHOLDER 2'
  log-validation-errors:
    id: job-log-id
    name: Log Validation Errors to Google Sheets
    adaptor: '@openfn/language-googlesheets@latest'
    body: 'PLACEHOLDER 3'
  transform-and-upload-to-dhis2:
    id: job-transform-id
    name: Transform and Upload to DHIS2
    adaptor: '@openfn/language-dhis2@latest'
    body: 'PLACEHOLER 4'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
edges:
  webhook->receive-commcare-data:
    id: edge-webhook-receive-id
    source_trigger: webhook
    target_job: receive-commcare-data
    condition_type: always
    enabled: true
  receive-commcare-data->validate-patient-data:
    id: edge-receive-validate-id
    source_job: receive-commcare-data
    target_job: validate-patient-data
    condition_type: on_job_success
    enabled: true
  validate-patient-data->log-validation-errors:
    id: edge-validate-log-id
    source_job: validate-patient-data
    target_job: log-validation-errors
    condition_type: on_job_failure
    enabled: true
  validate-patient-data->transform-and-upload-to-dhis2:
    id: edge-validate-transform-id
    source_job: validate-patient-data
    target_job: transform-and-upload-to-dhis2
    condition_type: on_job_success
    enabled: true
"""


def test_input_second_turn(apollo_client):
    payload = build_workflow_chat_payload(
        existing_yaml=EXISTING_YAML,
        history=[
            {
                "role": "user",
                "content": (
                    "Set up an OpenFn workflow to automatically receive new patient data from "
                    "CommCare, validate the data and if there's an issue log it to a google "
                    "sheet, otherwise map it to the DHIS2 data model, and load it into the "
                    "DHIS2 national health information system"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "I'll create a workflow to process CommCare patient data. The flow will "
                    "receive data via webhook, validate it, then either log issues to Google "
                    "Sheets or transform and send valid data to DHIS2."
                ),
            },
        ],
        user_message="Actually, let's add data deduplication before validation to prevent duplicate patient records",
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)
    assert_yaml_section_contains_all(EXISTING_YAML, response.get("response_yaml", ""), "jobs")
    assert_no_special_chars(response["response_yaml"])

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary

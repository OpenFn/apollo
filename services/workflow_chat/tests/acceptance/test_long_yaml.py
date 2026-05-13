"""Long workflow YAML + multi-turn history. The service should preserve every
existing job and edge while adding the new mailgun bulk-email step the user
requested. Tests that the response isn't truncated or stripped of structure."""

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import (
    assert_no_special_chars,
    assert_yaml_section_contains_all,
)


QUALITY_CRITERIA = [
    "The new bulk-email step is plausibly integrated into the existing pipeline (positioned after the Asana update, as the user requested).",
]


EXISTING_YAML = """
name: Data-Integration-and-Reporting
jobs:
  Retrieve-Google-Sheets-Data:
    id: job-retrieve-gsheets
    name: Retrieve Google Sheets Data
    adaptor: "@openfn/language-googlesheets@latest"
    body: // PLACEHOLDER 1
  Retrieve-NetSuite-Data:
    id: job-retrieve-netsuite
    name: Retrieve NetSuite Data
    adaptor: "@openfn/language-http@latest"
    body: // PLACEHOLDER 2
  Retrieve-Ferntech-Data:
    id: job-retrieve-ferntech
    name: Retrieve Ferntech Data
    adaptor: "@openfn/language-http@latest"
    body: // PLACEHOLDER 3
  Process-Combined-Data:
    id: job-process-combined
    name: Process Combined Data
    adaptor: "@openfn/language-common@latest"
    body: // PLACEHOLDER 4
  Send-Email-Report:
    id: job-send-email
    name: Send Email Report
    adaptor: "@openfn/language-gmail@latest"
    body: // PLACEHOLDER 5a
  write-to-sheet:
    id: job-write-sheet
    name: write to sheet
    adaptor: "@openfn/language-googlesheets@3.0.13"
    body: // PLACEHOLDER 5b
  Summarise-with-claude:
    id: job-summarise-claude
    name: Summarise with claude
    adaptor: "@openfn/language-claude@1.0.7"
    body: // PLACEHOLDER 5c
  Email-summary:
    id: job-email-summary
    name: Email summary
    adaptor: "@openfn/language-gmail@1.3.0"
    body: // PLACEHOLDER 6
  Update-asana:
    id: job-update-asana
    name: Update asana
    adaptor: "@openfn/language-asana@4.1.0"
    body: // PLACEHOLDER 7
triggers:
  webhook:
    id: trigger-webhook
    type: webhook
    enabled: false
edges:
  webhook->Retrieve-Google-Sheets-Data:
    id: edge-webhook-gsheets
    source_trigger: webhook
    target_job: Retrieve-Google-Sheets-Data
    condition_type: always
    enabled: true
  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:
    id: edge-gsheets-netsuite
    source_job: Retrieve-Google-Sheets-Data
    target_job: Retrieve-NetSuite-Data
    condition_type: on_job_success
    enabled: true
  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:
    id: edge-netsuite-ferntech
    source_job: Retrieve-NetSuite-Data
    target_job: Retrieve-Ferntech-Data
    condition_type: on_job_success
    enabled: true
  Retrieve-Ferntech-Data->Process-Combined-Data:
    id: edge-ferntech-combined
    source_job: Retrieve-Ferntech-Data
    target_job: Process-Combined-Data
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->Send-Email-Report:
    id: edge-combined-email
    source_job: Process-Combined-Data
    target_job: Send-Email-Report
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->write-to-sheet:
    id: edge-combined-sheet
    source_job: Process-Combined-Data
    target_job: write-to-sheet
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->Summarise-with-claude:
    id: edge-combined-summarise
    source_job: Process-Combined-Data
    target_job: Summarise-with-claude
    condition_type: on_job_success
    enabled: true
  Summarise-with-claude->Email-summary:
    id: edge-summarise-email
    source_job: Summarise-with-claude
    target_job: Email-summary
    condition_type: on_job_success
    enabled: true
  Email-summary->Update-asana:
    id: edge-email-asana
    source_job: Email-summary
    target_job: Update-asana
    condition_type: on_job_success
    enabled: true
"""


# History is shortened to user/assistant pairs — the full reproduction lives in
# the original test_qualitative.py and isn't needed to exercise the bug.
HISTORY = [
    {
        "role": "user",
        "content": (
            "I need to create a comprehensive data integration workflow that pulls "
            "data from Google Sheets, NetSuite, and Ferntech, then processes "
            "everything together and creates various reports and notifications."
        ),
    },
    {"role": "assistant", "content": "Absolutely! Let's start by setting up the workflow to retrieve data."},
    {"role": "user", "content": "Once the data is retrieved, I want to process all the combined data together."},
    {"role": "assistant", "content": "Great, I'll add a processing job."},
    {"role": "user", "content": "After processing, I want to send an email report and also write the results back to a Google Sheet."},
    {"role": "assistant", "content": "Understood. Added Send-Email-Report and write-to-sheet."},
    {"role": "user", "content": "Can we also use Claude AI to summarize the processed data, then email and update Asana?"},
    {"role": "assistant", "content": "Excellent — added Summarise-with-claude, Email-summary, Update-asana."},
    {"role": "user", "content": "Can you make sure the workflow is robust to errors in any of the data retrieval steps?"},
    {"role": "assistant", "content": "Added an error-handler with on_job_failure edges from each retrieval job."},
]


def test_long_yaml(apollo_client):
    payload = build_workflow_chat_payload(
        existing_yaml=EXISTING_YAML,
        history=HISTORY,
        user_message=(
            "Perfect! One final addition - after updating Asana, I want to format "
            "the data for bulk emailing and then send out bulk emails using Mailgun."
        ),
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)
    assert_yaml_section_contains_all(EXISTING_YAML, response.get("response_yaml", ""), "jobs")
    assert_yaml_section_contains_all(EXISTING_YAML, response.get("response_yaml", ""), "edges")
    assert_no_special_chars(response["response_yaml"])

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary

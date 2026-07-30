"""Unit tests for the shared inspect_job_code tool executor and redaction."""

from yaml_utils import inspect_job_code, redact_job_bodies

WORKFLOW_YAML = """\
name: wf
jobs:
  fetch-patients:
    name: Fetch Patients
    body: get('/patients');
  send-data:
    name: Send Data
    body: post('/data', $.data);
"""

WORKFLOW_YAML_WITH_IDS = """\
name: wf
jobs:
  fetch-patients:
    id: 5f2f36e7-3f42-4b0a-9c11-9b3f5a3d1a01
    name: Fetch Patients
    adaptor: "@openfn/language-http@latest"
    body: get('/patients');
triggers:
  webhook:
    id: 2d7f80b3-1c55-47a9-8e2f-6a90d24c7a03
    type: webhook
edges:
  webhook->fetch-patients:
    id: c4e9a1f6-0d82-4c37-9b54-7e315f68bd04
    source_trigger: webhook
    target_job: fetch-patients
    condition_type: always
"""


def test_redact_strips_bodies_and_ids_keeps_structure() -> None:
    redacted = redact_job_bodies(WORKFLOW_YAML_WITH_IDS)

    assert "get('/patients');" not in redacted
    assert "# [use inspect_job_code to view]" in redacted
    assert "id:" not in redacted
    # Structure the model needs stays intact
    assert "Fetch Patients" in redacted
    assert "@openfn/language-http@latest" in redacted
    assert "webhook->fetch-patients" in redacted
    assert "condition_type: always" in redacted


def test_inspect_returns_requested_bodies() -> None:
    result = inspect_job_code(WORKFLOW_YAML, ["fetch-patients", "send-data"])
    assert "get('/patients');" in result
    assert "post('/data', $.data);" in result


def test_inspect_matches_fuzzy_names() -> None:
    result = inspect_job_code(WORKFLOW_YAML, ["Fetch Patients"])
    assert "get('/patients');" in result


def test_inspect_reports_missing_job() -> None:
    result = inspect_job_code(WORKFLOW_YAML, ["nonexistent"])
    assert "No code found for job 'nonexistent'." in result


def test_inspect_handles_missing_yaml_and_keys() -> None:
    assert inspect_job_code(None, ["a"]) == "No workflow available to inspect."
    assert inspect_job_code(WORKFLOW_YAML, []) == "ERROR: No job keys provided."

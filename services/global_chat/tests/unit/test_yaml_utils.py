"""Unit tests for the shared inspect_job_code tool executor."""

from yaml_utils import inspect_job_code

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

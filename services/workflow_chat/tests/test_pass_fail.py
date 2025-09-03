import pytest
import json
import sys
import yaml
import tempfile
import subprocess
from pathlib import Path
import difflib
from typing import List
from .test_utils import assert_yaml_equal_except, call_workflow_chat_service, make_service_input, print_response_details, assert_no_special_chars, assert_yaml_jobs_have_body, assert_yaml_has_ids

def test_change_trigger():
    print("==================TEST==================")
    print("Description: This tests that the service can change the workflow trigger as requested without changing anything else in the YAML.")
    existing_yaml = """
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
    history = [
        {"role": "user", "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."},
        {"role": "assistant", "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"}
    ]
    content = "Actually I want to schedule it for midnight every day."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "change_trigger", content=content)
    assert response is not None
    assert isinstance(response, dict)
    
    # Check that the YAML trigger is now a cron trigger, not webhook
    yaml_str = response.get("response_yaml")
    assert yaml_str is not None, "No YAML returned in response_yaml"
    parsed = yaml.safe_load(yaml_str)
    triggers = parsed.get("triggers", {})
    assert "cron" in triggers, f"Expected 'cron' trigger, got: {triggers.keys()}"
    assert triggers["cron"].get("type") == "cron", f"Expected type 'cron', got: {triggers['cron'].get('type')}"
    assert triggers["cron"].get("cron_expression") == "0 0 * * *", f"Expected cron_expression '0 0 * * *', got: {triggers['cron'].get('cron_expression')}"
    assert "webhook" not in triggers, "webhook trigger should have been replaced by cron"

    # Use the reusable function to assert only triggers changed
    orig_yaml = yaml.safe_load(existing_yaml)
    assert_yaml_equal_except(
        orig_yaml, parsed,
        allowed_paths=["triggers", "edges"],
        context="YAML changed outside triggers or edges section."
    )


def test_rename_two_jobs_commcare():
    print("==================TEST==================")
    print("Description: This tests that the service can rename two jobs in a 4-job CommCare workflow, and only the job names change.")
    existing_yaml = """
name: commcare-case-sync
jobs:
  fetch-cases:
    id: job-fetch-id
    name: Fetch Cases from CommCare
    adaptor: '@openfn/language-commcare@latest'
    body: 'fetch_cases()'
  filter-cases:
    id: job-filter-id
    name: Filter Cases
    adaptor: '@openfn/language-common@latest'
    body: 'filter_cases()'
  transform-cases:
    id: job-transform-id
    name: Transform Case Data
    adaptor: '@openfn/language-common@latest'
    body: 'transform_cases()'
  send-to-fhir:
    id: job-fhir-id
    name: Send to FHIR
    adaptor: '@openfn/language-fhir@latest'
    body: 'send_to_fhir()'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
edges:
  webhook->fetch-cases:
    id: edge-webhook-fetch-id
    source_trigger: webhook
    target_job: fetch-cases
    condition_type: always
    enabled: true
  fetch-cases->filter-cases:
    id: edge-fetch-filter-id
    source_job: fetch-cases
    target_job: filter-cases
    condition_type: on_job_success
    enabled: true
  filter-cases->transform-cases:
    id: edge-filter-transform-id
    source_job: filter-cases
    target_job: transform-cases
    condition_type: on_job_success
    enabled: true
  transform-cases->send-to-fhir:
    id: edge-transform-fhir-id
    source_job: transform-cases
    target_job: send-to-fhir
    condition_type: on_job_success
    enabled: true
"""
    history = [
        {"role": "user", "content": "Sync CommCare cases to FHIR. Fetch cases, filter, transform, and send to FHIR."},
        {"role": "assistant", "content": "Here's a workflow that fetches cases from CommCare, filters and transforms them, then sends to FHIR.\n\n```\nname: commcare-case-sync\njobs:\n  fetch-cases:\n    name: Fetch Cases from CommCare\n    adaptor: '@openfn/language-commcare@latest'\n    body: '// Add operations here'\n  filter-cases:\n    name: Filter Cases\n    adaptor: '@openfn/language-common@latest'\n    body: '// Add operations here'\n  transform-cases:\n    name: Transform Case Data\n    adaptor: '@openfn/language-common@latest'\n    body: '// Add operations here'\n  send-to-fhir:\n    name: Send to FHIR\n    adaptor: '@openfn/language-fhir@latest'\n    body: '// Add operations here'\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->fetch-cases:\n    source_trigger: webhook\n    target_job: fetch-cases\n    condition_type: always\n    enabled: true\n  fetch-cases->filter-cases:\n    source_job: fetch-cases\n    target_job: filter-cases\n    condition_type: on_job_success\n    enabled: true\n  filter-cases->transform-cases:\n    source_job: filter-cases\n    target_job: transform-cases\n    condition_type: on_job_success\n    enabled: true\n  transform-cases->send-to-fhir:\n    source_job: transform-cases\n    target_job: send-to-fhir\n    condition_type: on_job_success\n    enabled: true\n```"},
        {"role": "user", "content": "Can you explain what each job does?"},
        {"role": "assistant", "content": "Sure! 'Fetch Cases from CommCare' retrieves cases, 'Filter Cases' narrows them down, 'Transform Case Data' prepares them for FHIR, and 'Send to FHIR' uploads them to the FHIR server."}
    ]
    content = "Please rename 'filter-cases' to 'screen-cases' and 'send-to-fhir' to 'upload-to-fhir'."

    target_yaml = """
name: commcare-case-sync
jobs:
  fetch-cases:
    id: job-fetch-id
    name: Fetch Cases from CommCare
    adaptor: '@openfn/language-commcare@latest'
    body: 'fetch_cases()'
  screen-cases:
    id: job-filter-id
    name: Screen Cases
    adaptor: '@openfn/language-common@latest'
    body: 'filter_cases()'
  transform-cases:
    id: job-transform-id
    name: Transform Case Data
    adaptor: '@openfn/language-common@latest'
    body: 'transform_cases()'
  upload-to-fhir:
    id: job-fhir-id
    name: Upload to FHIR
    adaptor: '@openfn/language-fhir@latest'
    body: 'send_to_fhir()'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
edges:
  webhook->fetch-cases:
    id: edge-webhook-fetch-id
    source_trigger: webhook
    target_job: fetch-cases
    condition_type: always
    enabled: true
  fetch-cases->screen-cases:
    id: edge-fetch-filter-id
    source_job: fetch-cases
    target_job: screen-cases
    condition_type: on_job_success
    enabled: true
  screen-cases->transform-cases:
    id: edge-filter-transform-id
    source_job: screen-cases
    target_job: transform-cases
    condition_type: on_job_success
    enabled: true
  transform-cases->upload-to-fhir:
    id: edge-transform-fhir-id
    source_job: transform-cases
    target_job: upload-to-fhir
    condition_type: on_job_success
    enabled: true
"""
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "rename_two_jobs_commcare", content=content)
    assert response is not None
    assert isinstance(response, dict)

    yaml_str = response.get("response_yaml")
    assert yaml_str is not None, "No YAML returned in response_yaml"
    parsed = yaml.safe_load(yaml_str)
    expected = yaml.safe_load(target_yaml)
    assert parsed == expected

def test_special_characters():
    print("==================TEST==================")
    print("Description: Ask for a workflow that uses platforms with special characters in their names. "
          "Verify that diacritics and punctuation removed/normalised correctly (e.g. é->e) in job names "
          "in the generated YAML.")
    existing_yaml = """"""
    history = [
        {"role": "user", "content": "Create a workflow that retrieves data from mwater, google sheets, netsuite, ferntech.io and processed it and sends it to frappé"},
        {"role": "assistant", "content": "I'll need more information about your workflow to create an accurate YAML. Specifically: What kind of data are you retrieving from each source (mWater, Google Sheets, NetSuite, ferntech.io)? What processing needs to be done on this data? What type of data needs to be sent to Frappé? Should this workflow run on a schedule or be triggered by an event? With these details, I can create a proper workflow structure for you."}
    ]
    content = "data about water systems and water sales"
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_water_bug", content=content)
    assert response is not None
    assert isinstance(response, dict)

    if response.get("response_yaml"):
        assert_yaml_has_ids(response["response_yaml"], context="test_special_characters")
        assert_yaml_jobs_have_body(response["response_yaml"], context="test_special_characters")
        assert_no_special_chars(response["response_yaml"], context="test_special_characters")

if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 
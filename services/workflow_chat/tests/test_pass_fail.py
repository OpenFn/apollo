import pytest
import json
import sys
import yaml
import tempfile
import subprocess
from pathlib import Path
import difflib
from typing import List
from .test_utils import assert_yaml_equal_except, call_workflow_chat_service, make_service_input, print_response_details

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

if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 
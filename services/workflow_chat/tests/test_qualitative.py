#!/usr/bin/env python3

import pytest
import json
import sys
import tempfile
import subprocess
from pathlib import Path
from .test_utils import call_workflow_chat_service, make_service_input, print_response_details, assert_yaml_section_contains_all
import yaml

# ---- TESTS ----
def test_basic_input():
    print("==================TEST==================")
    print("Description: Basic input test. Check if the service can handle a simple input "
          "without a YAML and generate a message and a YAML or ask for more information.")
    existing_yaml = """"""
    history = []
    content = "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_input", content=content)

    assert response is not None
    assert isinstance(response, dict)

def test_input_second_turn():
    print("Description: Simple second conversation turn requesting a change to the YAML")
    
    existing_yaml = """
name: CommCare-to-DHIS2-Patient-Integration
jobs:
  receive-commcare-data:
    name: Receive CommCare Patient Data
    adaptor: '@openfn/language-commcare@latest'
    body: 'PLACEHOLDER 1'
  validate-patient-data:
    name: Validate Patient Data
    adaptor: '@openfn/language-common@latest'
    body: 'PLACEHOLDER 2'
  log-validation-errors:
    name: Log Validation Errors to Google Sheets
    adaptor: '@openfn/language-googlesheets@latest'
    body: 'PLACEHOLDER 3'
  transform-and-upload-to-dhis2:
    name: Transform and Upload to DHIS2
    adaptor: '@openfn/language-dhis2@latest'
    body: 'PLACEHOLER 4'
triggers:
  webhook:
    type: webhook
    enabled: false
edges:
  webhook->receive-commcare-data:
    source_trigger: webhook
    target_job: receive-commcare-data
    condition_type: always
    enabled: true
  receive-commcare-data->validate-patient-data:
    source_job: receive-commcare-data
    target_job: validate-patient-data
    condition_type: on_job_success
    enabled: true
  validate-patient-data->log-validation-errors:
    source_job: validate-patient-data
    target_job: log-validation-errors
    condition_type: on_job_failure
    enabled: true
  validate-patient-data->transform-and-upload-to-dhis2:
    source_job: validate-patient-data
    target_job: transform-and-upload-to-dhis2
    condition_type: on_job_success
    enabled: true
"""
    
    history = [
        {
            "role": "user", 
            "content": "Set up an OpenFn workflow to automatically receive new patient data from CommCare, validate the data and if there's an issue log it to a google sheet, otherwise map it to the DHIS2 data model, and load it into the DHIS2 national health information system"
        },
        {
            "role": "assistant", 
            "content": '{"text":"I\'ll create a workflow to process CommCare patient data. The flow will receive data via webhook, validate it, then either log issues to Google Sheets or transform and send valid data to DHIS2. This creates four distinct jobs with appropriate connections and error handling.","yaml":"name: CommCare-to-DHIS2-Patient-Integration\\njobs:\\n  receive-commcare-data:\\n    name: Receive CommCare Patient Data\\n    adaptor: \\"@openfn/language-commcare@latest\\"\\n    body: \\"// Add operations here\\"\\n  validate-patient-data:\\n    name: Validate Patient Data\\n    adaptor: \\"@openfn/language-common@latest\\"\\n    body: \\"// Add operations here\\"\\n  log-validation-errors:\\n    name: Log Validation Errors to Google Sheets\\n    adaptor: \\"@openfn/language-googlesheets@latest\\"\\n    body: \\"// Add operations here\\"\\n  transform-and-upload-to-dhis2:\\n    name: Transform and Upload to DHIS2\\n    adaptor: \\"@openfn/language-dhis2@latest\\"\\n    body: \\"// Add operations here\\"\\ntriggers:\\n  webhook:\\n    type: webhook\\n    enabled: false\\nedges:\\n  webhook->receive-commcare-data:\\n    source_trigger: webhook\\n    target_job: receive-commcare-data\\n    condition_type: always\\n    enabled: true\\n  receive-commcare-data->validate-patient-data:\\n    source_job: receive-commcare-data\\n    target_job: validate-patient-data\\n    condition_type: on_job_success\\n    enabled: true\\n  validate-patient-data->log-validation-errors:\\n    source_job: validate-patient-data\\n    target_job: log-validation-errors\\n    condition_type: on_job_failure\\n    enabled: true\\n  validate-patient-data->transform-and-upload-to-dhis2:\\n    source_job: validate-patient-data\\n    target_job: transform-and-upload-to-dhis2\\n    condition_type: on_job_success\\n    enabled: true"}'
        }
    ]
    
    content = "Actually, let's add data deduplication before validation to prevent duplicate patient records"
    
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "commcare_dhis2_integration", content=content)
    
    assert response is not None
    assert isinstance(response, dict)

    assert_yaml_section_contains_all(existing_yaml, response.get("response_yaml", ""), "jobs", context="Jobs section")

def test_conversational_turn():
    print("==================TEST==================")
    print("Description: There is an existing YAML and the user asks a question that should not "
          "lead to a change in the YAML. Check the service only outputs a message, and no YAML, "
          "or an unchanged YAML.")
    existing_yaml = """
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-common@latest'
    body: '| // Add data parsing and aggregation operations here'
  upload-to-redis:
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: '| // Add Redis collection upload operations here'
triggers:
  webhook:
    type: webhook
    enabled: false
edges:
  webhook->parse-and-aggregate-fridge-data:
    source_trigger: webhook
    target_job: parse-and-aggregate-fridge-data
    condition_type: always
    enabled: true
  parse-and-aggregate-fridge-data->upload-to-redis:
    source_job: parse-and-aggregate-fridge-data
    target_job: upload-to-redis
    condition_type: on_job_success
    enabled: true 
"""
    history = [
        {"role": "user", "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."},
        {"role": "assistant", "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"}
    ]
    content = "Can you explain that better"
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "existing_convo_turn", content=content)
    assert response is not None
    assert isinstance(response, dict)

    response_yaml_str = response.get("response_yaml", None)
    if response_yaml_str and str(response_yaml_str).strip():
        orig_yaml = yaml.safe_load(existing_yaml)
        response_yaml = yaml.safe_load(response_yaml_str)
        # Check that the entire YAML is unchanged
        assert orig_yaml == response_yaml, "If YAML is present in response, it must be unchanged."

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

def test_simple_lang_bug():
    print("==================TEST==================")
    print("Description: Check how the service describes itself. It should use simple language and not mention YAMLs.")
    existing_yaml = """"""
    history = []
    content = "are you there?"
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_simple_lang_bug", content=content)
    assert response is not None
    assert isinstance(response, dict)
    # Assert that the response text does not include the word 'YAML' (case-insensitive)
    response_text = response.get("response", "")

    assert "yaml" not in response_text.lower(), f"Response text should not mention 'YAML', but got: {response_text}"

def test_single_trigger_node():
    print("==================TEST==================")
    print("Description: The user asks for a change that implies they want multiple nodes from the trigger. "
          "As only one node can come from the trigger, the service should select one job to be run first, "
          "and that one can have multiple nodes for the other jobs.")
    existing_yaml = """
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-common@latest'
    body: 'print("hello a")'
  upload-to-redis:
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: 'print("hello b")'
triggers:
  webhook:
    type: webhook
    enabled: false
edges:
  webhook->parse-and-aggregate-fridge-data:
    source_trigger: webhook
    target_job: parse-and-aggregate-fridge-data
    condition_type: always
    enabled: true
  parse-and-aggregate-fridge-data->upload-to-redis:
    source_job: parse-and-aggregate-fridge-data
    target_job: upload-to-redis
    condition_type: on_job_success
    enabled: true 
"""
    history = [
        {"role": "user", "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."},
        {"role": "assistant", "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"}
    ]
    content = "Actually I also want an email notification at the same time as the data is being parsed."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_trigger_nodes", content=content)

    assert response is not None
    assert isinstance(response, dict)

def test_edit_job_code():
    print("==================TEST==================")
    print("Description: The user asks for job code to be filled in. The service should explain why it can't. "
          "A new YAML should not be generated or it should be identical to the existing one.")
    existing_yaml = """
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-common@latest'
    body: 'print("hello a")'
  upload-to-redis:
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: 'print("hello a")'
triggers:
  webhook:
    type: webhook
    enabled: false
edges:
  webhook->parse-and-aggregate-fridge-data:
    source_trigger: webhook
    target_job: parse-and-aggregate-fridge-data
    condition_type: always
    enabled: true
  parse-and-aggregate-fridge-data->upload-to-redis:
    source_job: parse-and-aggregate-fridge-data
    target_job: upload-to-redis
    condition_type: on_job_success
    enabled: true 
"""
    history = [
        {"role": "user", "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."},
        {"role": "assistant", "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"}
    ]
    content = "Can you also fill in the job code for all the steps"
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "existing_edit_job_code", content=content)

    assert response is not None
    assert isinstance(response, dict)

def test_error_field():
    print("==================TEST==================")
    print("Description: This tests that the service can handle an error field input (that replaces the content field). "
          "Check that the service comments on the error and produces a new YAML.")
    existing_yaml = """
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-commons@latest'
    body: '| // Add data parsing and aggregation operations here'
  upload-to-redis:
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: '| // Add Redis collection upload operations here'
triggers:
  webhook:
    type: webhook
    enabled: false
edges:
  webhook->parse-and-aggregate-fridge-data:
    source_trigger: webhook
    target_job: parse-and-aggregate-fridge-data
    condition_type: always
    enabled: true
  parse-and-aggregate-fridge-data->upload-to-redis:
    source_job: parse-and-aggregate-fridge-data
    target_job: upload-to-redis
    condition_type: on_job_success
    enabled: true 
"""
    history = [
        {"role": "user", "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."},
        {"role": "assistant", "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"}
    ]
    errors = "adaptor error"
    # This test uses errors, so no content field

    service_input = make_service_input(existing_yaml, history, errors=errors)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "existing_error", errors=errors)

    assert response is not None
    assert isinstance(response, dict)

def test_long_yaml():
    print("==================TEST==================")
    print("Description: Test that the service can handle a slighly longer YAML & conversation history. "
          "Check that the answer isn't cut off or empty, and that all the job code is retained.")
    existing_yaml = """
name: Data-Integration-and-Reporting
jobs:
  Retrieve-Google-Sheets-Data:
    name: Retrieve Google Sheets Data
    adaptor: "@openfn/language-googlesheets@latest"
    body: // PLACEHOLDER 1
  Retrieve-NetSuite-Data:
    name: Retrieve NetSuite Data
    adaptor: "@openfn/language-http@latest"
    body: // PLACEHOLDER 2
  Retrieve-Ferntech-Data:
    name: Retrieve Ferntech Data
    adaptor: "@openfn/language-http@latest"
    body: // PLACEHOLDER 3
  Process-Combined-Data:
    name: Process Combined Data
    adaptor: "@openfn/language-common@latest"
    body: // PLACEHOLDER 4
  Send-Email-Report:
    name: Send Email Report
    adaptor: "@openfn/language-gmail@latest"
    body: // PLACEHOLDER 5a
  write-to-sheet:
    name: write to sheet
    adaptor: "@openfn/language-googlesheets@3.0.13"
    body: // PLACEHOLDER 5b
  Summarise-with-claude:
    name: Summarise with claude
    adaptor: "@openfn/language-claude@1.0.7"
    body: // PLACEHOLDER 5c
  Email-summary:
    name: Email summary
    adaptor: "@openfn/language-gmail@1.3.0"
    body: // PLACEHOLDER 6
  Update-asana:
    name: Update asana
    adaptor: "@openfn/language-asana@4.1.0"
    body: // PLACEHOLDER 7
triggers:
  webhook:
    type: webhook
    enabled: false
edges:
  webhook->Retrieve-Google-Sheets-Data:
    source_trigger: webhook
    target_job: Retrieve-Google-Sheets-Data
    condition_type: always
    enabled: true
  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:
    source_job: Retrieve-Google-Sheets-Data
    target_job: Retrieve-NetSuite-Data
    condition_type: on_job_success
    enabled: true
  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:
    source_job: Retrieve-NetSuite-Data
    target_job: Retrieve-Ferntech-Data
    condition_type: on_job_success
    enabled: true
  Retrieve-Ferntech-Data->Process-Combined-Data:
    source_job: Retrieve-Ferntech-Data
    target_job: Process-Combined-Data
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->Send-Email-Report:
    source_job: Process-Combined-Data
    target_job: Send-Email-Report
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->write-to-sheet:
    source_job: Process-Combined-Data
    target_job: write-to-sheet
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->Summarise-with-claude:
    source_job: Process-Combined-Data
    target_job: Summarise-with-claude
    condition_type: on_job_success
    enabled: true
  Summarise-with-claude->Email-summary:
    source_job: Summarise-with-claude
    target_job: Email-summary
    condition_type: on_job_success
    enabled: true
  Email-summary->Update-asana:
    source_job: Email-summary
    target_job: Update-asana
    condition_type: on_job_success
    enabled: true
"""
    history = [
        {"role": "user", "content": "I need to create a comprehensive data integration workflow that pulls data from Google Sheets, NetSuite, and Ferntech, then processes everything together and creates various reports and notifications."},
        {"role": "assistant", "content": "Absolutely! Let's start by setting up the workflow to retrieve data from Google Sheets, NetSuite, and Ferntech. I'll create jobs for each data source and connect them in sequence.\n\n```yaml\nname: Data-Integration-Workflow\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: '@openfn/language-googlesheets@latest'\n    body: // PLACEHOLDER 1\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 2\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 3\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n```"},
        {"role": "user", "content": "Once the data is retrieved, I want to process all the combined data together before generating any reports."},
        {"role": "assistant", "content": "Great, I'll add a processing job that takes the output from the three data retrieval jobs and combines the data for further use.\n\n```yaml\nname: Data-Integration-Workflow\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: '@openfn/language-googlesheets@latest'\n    body: // PLACEHOLDER 1\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 2\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 3\n  Process-Combined-Data:\n    name: Process Combined Data\n    adaptor: '@openfn/language-common@latest'\n    body: // PLACEHOLDER 4\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Ferntech-Data->Process-Combined-Data:\n    source_job: Retrieve-Ferntech-Data\n    target_job: Process-Combined-Data\n    condition_type: on_job_success\n    enabled: true\n```"},
        {"role": "user", "content": "After processing, I want to send an email report and also write the results back to a Google Sheet."},
        {"role": "assistant", "content": "Understood. I'll add two jobs: one to send an email report and another to write the processed data to a Google Sheet. Both will run after the processing step.\n\n```yaml\nname: Data-Integration-and-Reporting\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: '@openfn/language-googlesheets@latest'\n    body: // PLACEHOLDER 1\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 2\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 3\n  Process-Combined-Data:\n    name: Process Combined Data\n    adaptor: '@openfn/language-common@latest'\n    body: // PLACEHOLDER 4\n  Send-Email-Report:\n    name: Send Email Report\n    adaptor: '@openfn/language-gmail@latest'\n    body: // PLACEHOLDER 5a\n  write-to-sheet:\n    name: write to sheet\n    adaptor: '@openfn/language-googlesheets@3.0.13'\n    body: // PLACEHOLDER 5b\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Ferntech-Data->Process-Combined-Data:\n    source_job: Retrieve-Ferntech-Data\n    target_job: Process-Combined-Data\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Send-Email-Report:\n    source_job: Process-Combined-Data\n    target_job: Send-Email-Report\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->write-to-sheet:\n    source_job: Process-Combined-Data\n    target_job: write-to-sheet\n    condition_type: on_job_success\n    enabled: true\n```"},
        {"role": "user", "content": "Can we also use Claude AI to summarize the processed data, then email that summary, and update our Asana project with the results?"},
        {"role": "assistant", "content": "Excellent idea! I'll add a summarization job using Claude AI, followed by jobs to email the summary and update Asana. These will branch off after the processing step as well.\n\n```yaml\nname: Data-Integration-and-Reporting\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: '@openfn/language-googlesheets@latest'\n    body: // PLACEHOLDER 1\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 2\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 3\n  Process-Combined-Data:\n    name: Process Combined Data\n    adaptor: '@openfn/language-common@latest'\n    body: // PLACEHOLDER 4\n  Send-Email-Report:\n    name: Send Email Report\n    adaptor: '@openfn/language-gmail@latest'\n    body: // PLACEHOLDER 5a\n  write-to-sheet:\n    name: write to sheet\n    adaptor: '@openfn/language-googlesheets@3.0.13'\n    body: // PLACEHOLDER 5b\n  Summarise-with-claude:\n    name: Summarise with claude\n    adaptor: '@openfn/language-claude@1.0.7'\n    body: // PLACEHOLDER 5c\n  Email-summary:\n    name: Email summary\n    adaptor: '@openfn/language-gmail@1.3.0'\n    body: // PLACEHOLDER 6\n  Update-asana:\n    name: Update asana\n    adaptor: '@openfn/language-asana@4.1.0'\n    body: // PLACEHOLDER 7\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Ferntech-Data->Process-Combined-Data:\n    source_job: Retrieve-Ferntech-Data\n    target_job: Process-Combined-Data\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Send-Email-Report:\n    source_job: Process-Combined-Data\n    target_job: Send-Email-Report\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->write-to-sheet:\n    source_job: Process-Combined-Data\n    target_job: write-to-sheet\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Summarise-with-claude:\n    source_job: Process-Combined-Data\n    target_job: Summarise-with-claude\n    condition_type: on_job_success\n    enabled: true\n  Summarise-with-claude->Email-summary:\n    source_job: Summarise-with-claude\n    target_job: Email-summary\n    condition_type: on_job_success\n    enabled: true\n  Email-summary->Update-asana:\n    source_job: Email-summary\n    target_job: Update-asana\n    condition_type: on_job_success\n    enabled: true\n```"},
        {"role": "user", "content": "Can you make sure the workflow is robust to errors in any of the data retrieval steps?"},
        {"role": "assistant", "content": "Good point! I'll add error handling so that if any data retrieval job fails, the workflow will log the error and stop further processing.\n\n```yaml\nname: Data-Integration-and-Reporting\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: '@openfn/language-googlesheets@latest'\n    body: // PLACEHOLDER 1\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 2\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: '@openfn/language-http@latest'\n    body: // PLACEHOLDER 3\n  Process-Combined-Data:\n    name: Process Combined Data\n    adaptor: '@openfn/language-common@latest'\n    body: // PLACEHOLDER 4\n  Send-Email-Report:\n    name: Send Email Report\n    adaptor: '@openfn/language-gmail@latest'\n    body: // PLACEHOLDER 5a\n  write-to-sheet:\n    name: write to sheet\n    adaptor: '@openfn/language-googlesheets@3.0.13'\n    body: // PLACEHOLDER 5b\n  Summarise-with-claude:\n    name: Summarise with claude\n    adaptor: '@openfn/language-claude@1.0.7'\n    body: // PLACEHOLDER 5c\n  Email-summary:\n    name: Email summary\n    adaptor: '@openfn/language-gmail@1.3.0'\n    body: // PLACEHOLDER 6\n  Update-asana:\n    name: Update asana\n    adaptor: '@openfn/language-asana@4.1.0'\n    body: // PLACEHOLDER 7\n  error-handler:\n    name: Error Handler\n    adaptor: '@openfn/language-common@latest'\n    body: // Log error and stop workflow\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Ferntech-Data->Process-Combined-Data:\n    source_job: Retrieve-Ferntech-Data\n    target_job: Process-Combined-Data\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Send-Email-Report:\n    source_job: Process-Combined-Data\n    target_job: Send-Email-Report\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->write-to-sheet:\n    source_job: Process-Combined-Data\n    target_job: write-to-sheet\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Summarise-with-claude:\n    source_job: Process-Combined-Data\n    target_job: Summarise-with-claude\n    condition_type: on_job_success\n    enabled: true\n  Summarise-with-claude->Email-summary:\n    source_job: Summarise-with-claude\n    target_job: Email-summary\n    condition_type: on_job_success\n    enabled: true\n  Email-summary->Update-asana:\n    source_job: Email-summary\n    target_job: Update-asana\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Google-Sheets-Data->error-handler:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: error-handler\n    condition_type: on_job_failure\n    enabled: true\n  Retrieve-NetSuite-Data->error-handler:\n    source_job: Retrieve-NetSuite-Data\n    target_job: error-handler\n    condition_type: on_job_failure\n    enabled: true\n  Retrieve-Ferntech-Data->error-handler:\n    source_job: Retrieve-Ferntech-Data\n    target_job: error-handler\n    condition_type: on_job_failure\n    enabled: true\n```"}
    ]
    content = "Perfect! One final addition - after updating Asana, I want to format the data for bulk emailing and then send out bulk emails using Mailgun."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "existing_long", content=content)
    assert response is not None
    assert isinstance(response, dict)

    assert_yaml_section_contains_all(existing_yaml, response.get("response_yaml", ""), "jobs", context="Jobs section")
    assert_yaml_section_contains_all(existing_yaml, response.get("response_yaml", ""), "edges", context="Edges section")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
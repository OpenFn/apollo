#!/usr/bin/env python3

import pytest
import json
import sys
import tempfile
import subprocess
from pathlib import Path

def call_workflow_chat_service(service_input):
    """Call the workflow_chat service using the entry.py runner."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_input:
        json.dump(service_input, temp_input, indent=2)
        temp_input_path = temp_input.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_output:
        temp_output_path = temp_output.name
    try:
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "entry.py"),
            "workflow_chat",
            "--input", temp_input_path,
            "--output", temp_output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        if result.returncode != 0:
            raise Exception(f"Service call failed: {result.stderr}")
        with open(temp_output_path, 'r') as f:
            response = json.load(f)
        return response
    finally:
        try:
            os.unlink(temp_input_path)
            os.unlink(temp_output_path)
        except:
            pass

def print_response_details(response, test_name):
    """Print detailed response information like the original script."""
    if "response" in response:
        print("\n📝 WORKFLOW_CHAT RESPONSE:")
        print(json.dumps(response["response"], indent=2))
    if "response_yaml" in response:
        yaml_data = response["response_yaml"]
        if yaml_data and isinstance(yaml_data, str) and yaml_data.strip():
            print("\n📄 GENERATED YAML:")
            print(yaml_data)
        elif yaml_data and yaml_data is not None:
            print("\n📄 GENERATED YAML:")
            print(json.dumps(yaml_data, indent=2))
        else:
            print("\n📄 GENERATED YAML: None (workflow_chat provided only text description)")
    else:
        print("\n📄 GENERATED YAML: File not found")
    if "usage" in response:
        print("\n📊 TOKEN USAGE:")
        print(json.dumps(response["usage"], indent=2))

def make_service_input(existing_yaml, history, content=None, errors=None):
    service_input = {
        "existing_yaml": existing_yaml,
        "history": history
    }
    if content is not None:
        service_input["content"] = content
    if errors is not None:
        service_input["errors"] = errors
    return service_input

# ---- TESTS ----

def test_basic_input():
    print("\n=== TEST: Basic input ===")
    print("Description: Basic input test. Check if the service can handle a simple input without a YAML and generate a message and a YAML or ask for more information.")
    existing_yaml = """"""
    history = []
    content = "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_input")
    assert response is not None
    assert isinstance(response, dict)

def test_existing_yaml_input_second_turn():
    print("\n=== TEST: existing_yaml_gen_yaml_input_second_turn.yaml + history_gen_yaml_input_second_turn.json ===")
    print("Description: Simple second conversation turn requesting a change to the trigger of an existing YAML. Check the service gives a new YAML and only changes the trigger.")
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
    content = "Actually I want to schedule it for midnight every day."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "existing_input_second_turn")
    assert response is not None
    assert isinstance(response, dict)

def test_special_characters():
    print("\n=== TEST: Special characters in platform names===")
    print("Description: Ask for a workflow that uses platforms with special characters in their names. Verify that diacritics and punctuation removed/normalised correctly (e.g. é->e) in job names in the generated YAML.")
    existing_yaml = """"""
    history = [
        {"role": "user", "content": "Create a workflow that retrieves data from mwater, google sheets, netsuite, ferntech.io and processed it and sends it to frappé"},
        {"role": "assistant", "content": "I'll need more information about your workflow to create an accurate YAML. Specifically: What kind of data are you retrieving from each source (mWater, Google Sheets, NetSuite, ferntech.io)? What processing needs to be done on this data? What type of data needs to be sent to Frappé? Should this workflow run on a schedule or be triggered by an event? With these details, I can create a proper workflow structure for you."}
    ]
    content = "data about water systems and water sales"
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_water_bug")
    assert response is not None
    assert isinstance(response, dict)

def test_empty_yaml_simple_lang_bug():
    print("\n=== TEST: Simple language ===")
    print("Description: Check how the service describes itself. It should use simple language and not mention YAMLs.")
    existing_yaml = """"""
    history = []
    content = "are you there?"
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_simple_lang_bug")
    assert response is not None
    assert isinstance(response, dict)

def test_single_trigger_node():
    print("\n=== TEST: Single trigger node ===")
    print("Description: The user asks for a change that implies they want multiple nodes from the trigger. As only one node can come from the trigger, the service should select one job to be run first, and that one can have multiple nodes for the other jobs.")
    existing_yaml = """"""
    history = [
        {"role": "user", "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."},
        {"role": "assistant", "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"}
    ]
    content = "Actually I also want an email notification at the same time as the data is being parsed."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "empty_trigger_nodes")
    assert response is not None
    assert isinstance(response, dict)

def test_existing_yaml_convo_turn():
    print("\n=== TEST: Conversation turn with existing YAML ===")
    print("Description: There is an existing YAML and the user asks a question that should not lead to a change in the YAML. Check the service only outputs a message, and no YAML or an unchanged YAML.")
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
    print_response_details(response, "existing_convo_turn")
    assert response is not None
    assert isinstance(response, dict)

def test_edit_job_code():
    print("\n=== TEST: Ask to edit job code ===")
    print("Description: The user asks for job code to be filled in. The service should explain why it can't. A new YAML should not be generated or it should be identical to the existing one.")
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
    print_response_details(response, "existing_edit_job_code")
    assert response is not None
    assert isinstance(response, dict)


def test_existing_yaml_error():
    print("\n=== TEST: existing_yaml_gen_yaml_error.yaml + history_gen_yaml_error.json (with errors) ===")
    print("Description: [TODO: fill in what this test is for]")
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
    # This test uses errors, so no content field
    service_input = make_service_input(existing_yaml, history, errors="adaptor error")
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "existing_error")
    assert response is not None
    assert isinstance(response, dict)

def test_existing_yaml_long():
    print("\n=== TEST: existing_yaml_long.yaml + history_gen_yaml_long.json ===")
    print("Description: [TODO: fill in what this test is for]")
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
  format-data:
    name: format data
    adaptor: "@openfn/language-common@latest"
    body: |
      // PLACEHOLDER 8
  email-bulk:
    name: email bulk
    adaptor: "@openfn/language-mailgun@0.5.13"
    body: // PLACEHOLDER 9
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
  Update-asana->format-data:
    source_job: Update-asana
    target_job: format-data
    condition_type: on_job_success
    enabled: true
  format-data->email-bulk:
    source_job: format-data
    target_job: email-bulk
    condition_type: on_job_success
    enabled: true
"""
    history = [
        {"role": "user", "content": "I need to create a comprehensive data integration workflow that pulls data from Google Sheets, NetSuite, and Ferntech, then processes everything together and creates various reports and notifications."},
        {"role": "assistant", "content": "I'll help you create a comprehensive data integration workflow. Let me start with the basic structure for retrieving data from your three sources:\n\n```yaml\nname: Data-Integration-Workflow\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: \"@openfn/language-googlesheets@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Google-Sheets-Data__\"\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-NetSuite-Data__\"\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Ferntech-Data__\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n```"},
        {"role": "user", "content": "Great! Now I need to process all that combined data together, and then I want to send an email report and also write the results back to a Google Sheet."},
        {"role": "assistant", "content": "Perfect! I'll add the data processing step and the two output jobs. Let me update the workflow:\n\n```yaml\nname: Data-Integration-and-Reporting\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: \"@openfn/language-googlesheets@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Google-Sheets-Data__\"\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-NetSuite-Data__\"\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Ferntech-Data__\"\n  Process-Combined-Data:\n    name: Process Combined Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"__CODE_BLOCK_Process-Combined-Data__\"\n  Send-Email-Report:\n    name: Send Email Report\n    adaptor: \"@openfn/language-gmail@latest\"\n    body: \"__CODE_BLOCK_Send-Email-Report__\"\n  write-to-sheet:\n    name: write to sheet\n    adaptor: \"@openfn/language-googlesheets@3.0.13\"\n    body: \"__CODE_BLOCK_write-to-sheet__\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Ferntech-Data->Process-Combined-Data:\n    source_job: Retrieve-Ferntech-Data\n    target_job: Process-Combined-Data\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Send-Email-Report:\n    source_job: Process-Combined-Data\n    target_job: Send-Email-Report\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->write-to-sheet:\n    source_job: Process-Combined-Data\n    target_job: write-to-sheet\n    condition_type: on_job_success\n    enabled: true\n```"},
        {"role": "user", "content": "I also want to use Claude AI to summarize the processed data, then email that summary, and update our Asana project with the results."},
        {"role": "assistant", "content": "Excellent idea! I'll add the Claude summarization step and the subsequent email and Asana updates. This creates a nice parallel branch for AI-powered insights:\n\n```yaml\nname: Data-Integration-and-Reporting\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: \"@openfn/language-googlesheets@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Google-Sheets-Data__\"\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-NetSuite-Data__\"\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Ferntech-Data__\"\n  Process-Combined-Data:\n    name: Process Combined Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"__CODE_BLOCK_Process-Combined-Data__\"\n  Send-Email-Report:\n    name: Send Email Report\n    adaptor: \"@openfn/language-gmail@latest\"\n    body: \"__CODE_BLOCK_Send-Email-Report__\"\n  write-to-sheet:\n    name: write to sheet\n    adaptor: \"@openfn/language-googlesheets@3.0.13\"\n    body: \"__CODE_BLOCK_write-to-sheet__\"\n  Summarise-with-claude:\n    name: Summarise with claude\n    adaptor: \"@openfn/language-claude@1.0.7\"\n    body: \"__CODE_BLOCK_Summarise-with-claude__\"\n  Email-summary:\n    name: Email summary\n    adaptor: \"@openfn/language-gmail@1.3.0\"\n    body: \"__CODE_BLOCK_Email-summary__\"\n  Update-asana:\n    name: Update asana\n    adaptor: \"@openfn/language-asana@4.1.0\"\n    body: \"__CODE_BLOCK_Update-asana__\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Ferntech-Data->Process-Combined-Data:\n    source_job: Retrieve-Ferntech-Data\n    target_job: Process-Combined-Data\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Send-Email-Report:\n    source_job: Process-Combined-Data\n    target_job: Send-Email-Report\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->write-to-sheet:\n    source_job: Process-Combined-Data\n    target_job: write-to-sheet\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Summarise-with-claude:\n    source_job: Process-Combined-Data\n    target_job: Summarise-with-claude\n    condition_type: on_job_success\n    enabled: true\n  Summarise-with-claude->Email-summary:\n    source_job: Summarise-with-claude\n    target_job: Email-summary\n    condition_type: on_job_success\n    enabled: true\n  Email-summary->Update-asana:\n    source_job: Email-summary\n    target_job: Update-asana\n    condition_type: on_job_success\n    enabled: true\n```"},
        {"role": "user", "content": "Perfect! One final addition - after updating Asana, I want to format the data for bulk emailing and then send out bulk emails using Mailgun."},
        {"role": "assistant", "content": "Perfect! I'll add the final steps for data formatting and bulk email distribution. This completes your comprehensive workflow:\n\n```yaml\nname: Data-Integration-and-Reporting\njobs:\n  Retrieve-Google-Sheets-Data:\n    name: Retrieve Google Sheets Data\n    adaptor: \"@openfn/language-googlesheets@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Google-Sheets-Data__\"\n  Retrieve-NetSuite-Data:\n    name: Retrieve NetSuite Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-NetSuite-Data__\"\n  Retrieve-Ferntech-Data:\n    name: Retrieve Ferntech Data\n    adaptor: \"@openfn/language-http@latest\"\n    body: \"__CODE_BLOCK_Retrieve-Ferntech-Data__\"\n  Process-Combined-Data:\n    name: Process Combined Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"__CODE_BLOCK_Process-Combined-Data__\"\n  Send-Email-Report:\n    name: Send Email Report\n    adaptor: \"@openfn/language-gmail@latest\"\n    body: \"__CODE_BLOCK_Send-Email-Report__\"\n  write-to-sheet:\n    name: write to sheet\n    adaptor: \"@openfn/language-googlesheets@3.0.13\"\n    body: \"__CODE_BLOCK_write-to-sheet__\"\n  Summarise-with-claude:\n    name: Summarise with claude\n    adaptor: \"@openfn/language-claude@1.0.7\"\n    body: \"__CODE_BLOCK_Summarise-with-claude__\"\n  Email-summary:\n    name: Email summary\n    adaptor: \"@openfn/language-gmail@1.3.0\"\n    body: \"__CODE_BLOCK_Email-summary__\"\n  Update-asana:\n    name: Update asana\n    adaptor: \"@openfn/language-asana@4.1.0\"\n    body: \"__CODE_BLOCK_Update-asana__\"\n  format-data:\n    name: format data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"__CODE_BLOCK_format-data__\"\n  email-bulk:\n    name: email bulk\n    adaptor: \"@openfn/language-mailgun@0.5.13\"\n    body: \"__CODE_BLOCK_email-bulk__\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->Retrieve-Google-Sheets-Data:\n    source_trigger: webhook\n    target_job: Retrieve-Google-Sheets-Data\n    condition_type: always\n    enabled: true\n  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:\n    source_job: Retrieve-Google-Sheets-Data\n    target_job: Retrieve-NetSuite-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:\n    source_job: Retrieve-NetSuite-Data\n    target_job: Retrieve-Ferntech-Data\n    condition_type: on_job_success\n    enabled: true\n  Retrieve-Ferntech-Data->Process-Combined-Data:\n    source_job: Retrieve-Ferntech-Data\n    target_job: Process-Combined-Data\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Send-Email-Report:\n    source_job: Process-Combined-Data\n    target_job: Send-Email-Report\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->write-to-sheet:\n    source_job: Process-Combined-Data\n    target_job: write-to-sheet\n    condition_type: on_job_success\n    enabled: true\n  Process-Combined-Data->Summarise-with-claude:\n    source_job: Process-Combined-Data\n    target_job: Summarise-with-claude\n    condition_type: on_job_success\n    enabled: true\n  Summarise-with-claude->Email-summary:\n    source_job: Summarise-with-claude\n    target_job: Email-summary\n    condition_type: on_job_success\n    enabled: true\n  Email-summary->Update-asana:\n    source_job: Email-summary\n    target_job: Update-asana\n    condition_type: on_job_success\n    enabled: true\n  Update-asana->format-data:\n    source_job: Update-asana\n    target_job: format-data\n    condition_type: on_job_success\n    enabled: true\n  format-data->email-bulk:\n    source_job: format-data\n    target_job: email-bulk\n    condition_type: on_job_success\n    enabled: true\n```\n\nYour workflow is now complete! It handles data integration from three sources, processes everything together, creates multiple types of reports and summaries, updates project management tools, and finishes with bulk email distribution. This gives you a comprehensive data pipeline with multiple output channels."},
        {"role": "user", "content": "Can I add one last step to write the formatted data to a google sheet?"}
    ]
    content = "Perfect! One final addition - after updating Asana, I want to format the data for bulk emailing and then send out bulk emails using Mailgun."
    service_input = make_service_input(existing_yaml, history, content=content)
    response = call_workflow_chat_service(service_input)
    print_response_details(response, "existing_long")
    assert response is not None
    assert isinstance(response, dict)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
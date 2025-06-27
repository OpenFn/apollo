# Workflow Chat Testing Guide

This directory contains tests for the `workflow_chat` service, designed to help development and ensure that basic abilities are not broken during changes. These are not extensive ML evaluations for answer quality, but quick checks to catch problems and verify core functionality when developing.

## Types of Tests

### 1. Qualitative Tests (`test_qualitative.py`)
- **Purpose:** Give a detailed view of the service's output for a variety of scenarios.
- **How to use:** The `print_response_details` function prints the full response, YAML, and token usage for each test. The `Description` in each test explains the goal and what to look for.
- **Intended for:** Manual review or LLM-assisted review during development. Useful for checking output contents and conversational behavior.

### 2. Pass/Fail Tests (`test_pass_fail.py`)
- **Purpose:** Check that specific changes are made correctly (e.g., only the trigger changes, job code and other YAML is preserved). These tests are more focused and print less output.
- **Intended for:** Automated checks to ensure that key behaviors are not broken by code changes.

## Running the Tests

You can run all tests or individual test files using `pytest`. The `-v` flag gives verbose output, and `-s` allows print statements to show in the console.

### Run all tests:
```bash
pytest -v -s
```

### Run a specific test file:
```bash
pytest test_qualitative.py -v -s
pytest test_pass_fail.py -v -s
```

### Run a single test function:
```bash
pytest test_pass_fail.py::test_change_trigger -v -s
```

## Notes
- These tests are for development and quick validation, not for comprehensive ML model evaluation.
- Review the `Description` in each test for what to check, especially in qualitative tests.
- All tests use the helpers in `test_utils.py` to call the service and check results.

## Input Format

### YAML File
A standard OpenFn workflow YAML file containing jobs, triggers, and edges.

### History File
A JSON file containing an array of conversation turns with "role" and "content" fields:
```json
[
  {
    "role": "user",
    "content": "User message 1"
  },
  {
    "role": "assistant", 
    "content": "Assistant response 1"
  },
  {
    "role": "user",
    "content": "User message 2"
  }
]
```

The script automatically:
- Removes the last user message and uses it as the "content" field
- Formats the remaining messages as conversation history
- Calls the workflow_chat service via entry.py
- Outputs results to `workflow_chat/test_outputs/`

## Output Files

For each test run, four files are generated:
- `{base_name}_response.json` - The text response from the service
- `{base_name}_response_yaml.yaml` - The generated YAML (if any)
- `{base_name}_history.json` - Updated conversation history
- `{base_name}_usage.json` - Token usage statistics

## Example Test Files

- `test_inputs/existing_yaml_a.yaml` & `test_inputs/history_a.json` - Basic workflow modification
- `test_inputs/existing_yaml_b.yaml` & `test_inputs/history_b.txt` - Trigger type change

The `tmp/` directory contains the original test files and should remain untouched. 
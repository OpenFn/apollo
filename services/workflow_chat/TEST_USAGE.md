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
# Job Chat Testing Guide

This directory contains tests for the `job_chat` service, designed to help with development and ensure core functionality remains intact. These tests verify that the AI chat assistant can correctly understand and modify OpenFn job code based on user requests.

## Types of Tests

### 1. Qualitative Tests (`test_qualitative.py`)

- **Purpose:** Provide detailed examples of the service's output for various scenarios where the assistant needs to modify code or answer questions.
- **How to use:** The tests print full responses and suggested code. The test descriptions explain what functionality is being tested.
- **Intended for:** Manual review during development to verify the assistant's ability to understand and modify job code correctly.

### 2. Pass/Fail Tests (`test_pass_fail.py`)

- **Purpose:** Verify that the service processes context and makes specific code changes correctly, with strict assertions checking that output matches expected results.
- **Examples:** Renaming variables, converting request types, handling duplicate sections, etc.
- **Intended for:** Automated testing to ensure core context handling and code modification abilities aren't broken.

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

### Run a specific test function:

```bash
pytest test_pass_fail.py::test_rename_variable -v -s
```

## Key Testing Parameters

- **suggest_code:** When set to `True`, tests the new structured response format with separate `suggested_code` field. When `False`, tests the original format with code embedded in the response text.
- **context fields:** Tests verify that the service can access and utilize all context fields (expression, input, output, log, etc.)
- **duplicate sections:** Tests ensure that the service can correctly identify and modify specific sections in code with multiple similar patterns.

## Notes

- These tests verify both the standard prompt format and backward compatibility mode.
- Review the printed outputs during test runs to see detailed information about service responses.
- The helper functions in `test_utils.py` provide utilities for calling the service and checking results.
# Workflow Chat Testing Script

This directory contains a standalone testing script for the workflow_chat service.

## Usage

From the `services/` directory, run:

```bash
conda activate openfn
python workflow_chat/run_test.py --existing_yaml workflow_chat/test_inputs/existing_yaml_a.yaml --history workflow_chat/test_inputs/history_a.json
```

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
"""Service-tier helpers for workflow_chat."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def call_workflow_chat_service(service_input):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_input:
        json.dump(service_input, temp_input, indent=2)
        temp_input_path = temp_input.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_output:
        temp_output_path = temp_output.name
    try:
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent.parent / "entry.py"),
            "workflow_chat",
            "--input",
            temp_input_path,
            "--output",
            temp_output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        if result.returncode != 0:
            raise Exception(f"Service call failed: {result.stderr}")
        with open(temp_output_path, "r") as f:
            response = json.load(f)
        return response
    finally:
        import os

        try:
            os.unlink(temp_input_path)
            os.unlink(temp_output_path)
        except Exception:
            pass


def make_service_input(existing_yaml, history, content=None, errors=None, context=None, meta=None):
    service_input = {"existing_yaml": existing_yaml, "history": history}
    if content is not None:
        service_input["content"] = content
    if errors is not None:
        service_input["errors"] = errors
    if context is not None:
        service_input["context"] = context
    if meta is not None:
        service_input["meta"] = meta
    return service_input


def print_response_details(response, content=None, errors=None):
    """Print detailed response information including content or errors if provided."""
    if content is not None:
        print("\nUSER CONTENT:")
        print(content)
    if errors is not None:
        print("\nERROR FIELD INPUT:")
        print(errors)
    if "response" in response:
        print("\nWORKFLOW_CHAT RESPONSE:")
        print(json.dumps(response["response"], indent=2))
    if "response_yaml" in response:
        yaml_data = response["response_yaml"]
        if yaml_data and isinstance(yaml_data, str) and yaml_data.strip():
            print("\nGENERATED YAML:")
            print(yaml_data)
        elif yaml_data and yaml_data is not None:
            print("\nGENERATED YAML:")
            print(json.dumps(yaml_data, indent=2))
        else:
            print("\nGENERATED YAML: None (workflow_chat provided only text description)")
    else:
        print("\nGENERATED YAML: File not found")
    if "usage" in response:
        print("\nTOKEN USAGE:")
        print(json.dumps(response["usage"], indent=2))

#!/usr/bin/env python3

import argparse
import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path


def read_yaml_file(yaml_path):
    """Read YAML file and return as string with proper newline formatting."""
    with open(yaml_path, 'r') as f:
        content = f.read()
    return content


def read_history_file(history_path, expect_user_message=True):
    """
    Read history file and parse it into conversation turns.
    Expected format: JSON array with objects containing "role" and "content" fields. 
    If expect_user_message is True, the last turn will be used as the user "content" for the workflow_chat service.
    Returns: (history_list, last_user_content)
    """
    with open(history_path, 'r') as f:
        history_data = json.load(f)
    
    if not isinstance(history_data, list):
        raise ValueError("History file must contain a JSON array of conversation turns")
    
    for i, turn in enumerate(history_data):
        if not isinstance(turn, dict) or "role" not in turn or "content" not in turn:
            raise ValueError(f"Turn {i} must be an object with 'role' and 'content' fields")
    
    last_user_content = ""
    history = history_data.copy()
    
    # Only remove the last turn if it's from the user and we expect a user message
    if expect_user_message and history and history[-1]["role"] == "user":
        last_user_content = history[-1]["content"]
        history = history[:-1]
    
    return history, last_user_content


def create_service_input(existing_yaml_path, history_path, errors=None):
    """Create the input JSON for the workflow_chat service."""
    existing_yaml = read_yaml_file(existing_yaml_path)
    
    expect_user_message = errors is None
    
    history, content = read_history_file(history_path, expect_user_message)
    
    # Create the service input
    service_input = {
        "existing_yaml": existing_yaml,
        "history": history
    }
    
    if content:
        service_input["content"] = content
    
    if errors:
        service_input["errors"] = errors
    
    return service_input


def ensure_output_directory():
    """Ensure the test_outputs directory exists."""
    output_dir = Path(__file__).parent / "test_outputs"
    output_dir.mkdir(exist_ok=True)
    return output_dir


def call_workflow_chat_service(service_input):
    """Call the workflow_chat service using entry.py."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_input:
        json.dump(service_input, temp_input, indent=2)
        temp_input_path = temp_input.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_output:
        temp_output_path = temp_output.name
    
    try:
        cmd = [
            sys.executable, 
            "entry.py", 
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


def write_output_files(response, base_filename, output_dir):
    """Write the response to separate files for each key."""
    # The response should have keys: response, response_yaml, history, usage
    for key, value in response.items():
        
        if key == "response_yaml" and isinstance(value, str) and value.strip():
            # Write YAML content as a .yaml file instead
            yaml_file = output_dir / f"{base_filename}_{key}.yaml"
            with open(yaml_file, 'w') as f:
                f.write(value)
            print(f"  Wrote {key} to {yaml_file}")
        else:
            output_file = output_dir / f"{base_filename}_{key}.json"
            with open(output_file, 'w') as f:
                json.dump(value, f, indent=2)
            print(f"  Wrote {key} to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Test workflow_chat service with YAML and history files")
    parser.add_argument("--existing_yaml", required=True, help="Path to existing YAML file")
    parser.add_argument("--history", required=True, help="Path to history text file")
    parser.add_argument("--errors", help="Error message to pass to workflow_chat service")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.existing_yaml):
        print(f"Error: YAML file not found: {args.existing_yaml}")
        sys.exit(1)
    
    if not os.path.exists(args.history):
        print(f"Error: History file not found: {args.history}")
        sys.exit(1)
    
    try:
        print("Reading input files...")
        service_input = create_service_input(args.existing_yaml, args.history, args.errors)
        
        print("Calling workflow_chat service...")
        response = call_workflow_chat_service(service_input)
        
        output_dir = ensure_output_directory()
        
        yaml_name = Path(args.existing_yaml).stem
        history_name = Path(args.history).stem
        base_filename = f"{yaml_name}_{history_name}"
        
        if args.errors:
            base_filename += "_errors"
        
        print(f"Writing output files with base name: {base_filename}")
        write_output_files(response, base_filename, output_dir)
        
        print("Test completed successfully!")
        
    except Exception as e:
        print(f"Error during test execution: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main() 
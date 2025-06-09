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


def read_history_file(history_path):
    """
    Read history file and parse it into conversation turns.
    Expected format: alternating user/assistant messages separated by blank lines or some delimiter.
    Returns: (history_list, last_user_content)
    """
    with open(history_path, 'r') as f:
        content = f.read().strip()
    
    # TODO change this to list with roles
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    
    history = []
    last_user_content = ""
    
    # Parse lines into alternating user/assistant turns
    for i, line in enumerate(lines):
        role = "user" if i % 2 == 0 else "assistant"
        history.append({"role": role, "content": line})
    
    # Remove the last turn if it's from the user and use it as content
    if history and history[-1]["role"] == "user":
        last_user_content = history[-1]["content"]
        history = history[:-1]
    
    return history, last_user_content


def create_service_input(existing_yaml_path, history_path):
    """Create the input JSON for the workflow_chat service."""
    # Read and format the existing YAML
    existing_yaml = read_yaml_file(existing_yaml_path)
    
    # Read and parse the history
    history, content = read_history_file(history_path)
    
    # Create the service input
    service_input = {
        "content": content,
        "existing_yaml": existing_yaml,
        "history": history
    }
    
    return service_input


def ensure_output_directory():
    """Ensure the test_outputs directory exists."""
    output_dir = Path(__file__).parent / "test_outputs"
    output_dir.mkdir(exist_ok=True)
    return output_dir


def call_workflow_chat_service(service_input):
    """Call the workflow_chat service using entry.py."""
    # Create a temporary input file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_input:
        json.dump(service_input, temp_input, indent=2)
        temp_input_path = temp_input.name
    
    # Create a temporary output file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_output:
        temp_output_path = temp_output.name
    
    try:
        # Call entry.py with the workflow_chat service
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
        
        # Read the response from the output file
        with open(temp_output_path, 'r') as f:
            response = json.load(f)
        
        return response
        
    finally:
        # Clean up temporary files
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
            # Write as JSON
            output_file = output_dir / f"{base_filename}_{key}.json"
            with open(output_file, 'w') as f:
                json.dump(value, f, indent=2)
            print(f"  Wrote {key} to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Test workflow_chat service with YAML and history files")
    parser.add_argument("--existing_yaml", required=True, help="Path to existing YAML file")
    parser.add_argument("--history", required=True, help="Path to history text file")
    
    args = parser.parse_args()
    
    # Validate input files exist
    if not os.path.exists(args.existing_yaml):
        print(f"Error: YAML file not found: {args.existing_yaml}")
        sys.exit(1)
    
    if not os.path.exists(args.history):
        print(f"Error: History file not found: {args.history}")
        sys.exit(1)
    
    try:
        # Create service input
        print("Reading input files...")
        service_input = create_service_input(args.existing_yaml, args.history)
        
        # Call the workflow_chat service via entry.py
        print("Calling workflow_chat service...")
        response = call_workflow_chat_service(service_input)
        
        # Ensure output directory exists
        output_dir = ensure_output_directory()
        
        # Generate base filename from input files
        yaml_name = Path(args.existing_yaml).stem
        history_name = Path(args.history).stem
        base_filename = f"{yaml_name}_{history_name}"
        
        # Write output files
        print(f"Writing output files with base name: {base_filename}")
        write_output_files(response, base_filename, output_dir)
        
        print("Test completed successfully!")
        
    except Exception as e:
        print(f"Error during test execution: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main() 
#!/usr/bin/env python3

import pytest
import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path


class WorkflowChatTester:
    """Helper class to encapsulate the workflow chat testing logic."""
    
    def __init__(self):
        self.output_dir = Path(__file__).parent / "test_outputs"
        self.output_dir.mkdir(exist_ok=True)
    
    def read_yaml_file(self, yaml_path):
        """Read YAML file and return as string."""
        with open(yaml_path, 'r') as f:
            return f.read()
    
    def read_history_file(self, history_path, expect_user_message=True):
        """Read history file and parse conversation turns."""
        with open(history_path, 'r') as f:
            history_data = json.load(f)
        
        if not isinstance(history_data, list):
            raise ValueError("History file must contain a JSON array")
        
        last_user_content = ""
        history = history_data.copy()
        
        if expect_user_message and history and history[-1]["role"] == "user":
            last_user_content = history[-1]["content"]
            history = history[:-1]
        
        return history, last_user_content
    
    def create_service_input(self, yaml_path, history_path, errors=None):
        """Create input JSON for workflow_chat service."""
        existing_yaml = self.read_yaml_file(yaml_path)
        expect_user_message = errors is None
        history, content = self.read_history_file(history_path, expect_user_message)
        
        service_input = {
            "existing_yaml": existing_yaml,
            "history": history
        }
        
        if content and content.strip():
            service_input["content"] = content
        
        if errors:
            service_input["errors"] = errors
        
        return service_input
    
    def call_workflow_chat_service(self, service_input):
        """Call the workflow_chat service."""
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
    
    def save_response(self, response, test_name):
        """Save response to output files."""
        for key, value in response.items():
            if key == "response_yaml" and isinstance(value, str) and value.strip():
                yaml_file = self.output_dir / f"{test_name}_{key}.yaml"
                with open(yaml_file, 'w') as f:
                    f.write(value)
            else:
                output_file = self.output_dir / f"{test_name}_{key}.json"
                with open(output_file, 'w') as f:
                    json.dump(value, f, indent=2)
        
        return response
    
    def print_response_details(self, response, test_name):
        """Print detailed response information like the original script."""
        # Print the main response JSON
        if "response" in response:
            print("\n📝 WORKFLOW_CHAT RESPONSE:")
            print(json.dumps(response["response"], indent=2))
        
        # Print the YAML output
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
        
        # Print usage information
        if "usage" in response:
            print("\n📊 TOKEN USAGE:")
            print(json.dumps(response["usage"], indent=2))


# Test data - this replaces your tests_to_run.txt
TEST_CASES = [
    ("workflow_chat/test_inputs/empty.yaml", "workflow_chat/test_inputs/history_gen_yaml_water_bug.json", None),
    ("workflow_chat/test_inputs/empty.yaml", "workflow_chat/test_inputs/history_gen_yaml_simple_lang_bug.json", None),
    ("workflow_chat/test_inputs/empty.yaml", "workflow_chat/test_inputs/history_gen_yaml_input.json", None),
    ("workflow_chat/test_inputs/empty.yaml", "workflow_chat/test_inputs/history_gen_yaml_trigger_nodes.json", None),
    ("workflow_chat/test_inputs/existing_yaml_gen_yaml_convo_turn.yaml", "workflow_chat/test_inputs/history_gen_yaml_convo_turn.json", None),
    ("workflow_chat/test_inputs/existing_yaml_gen_yaml_edit_job_code.yaml", "workflow_chat/test_inputs/history_gen_yaml_edit_job_code.json", None),
    ("workflow_chat/test_inputs/existing_yaml_gen_yaml_input_second_turn.yaml", "workflow_chat/test_inputs/history_gen_yaml_input_second_turn.json", None),
    ("workflow_chat/test_inputs/existing_yaml_gen_yaml_ask_job_code.yaml", "workflow_chat/test_inputs/history_gen_yaml_ask_job_code.json", None),
    ("workflow_chat/test_inputs/existing_yaml_gen_yaml_error.yaml", "workflow_chat/test_inputs/history_gen_yaml_error.json", "adaptor error"),
    ("workflow_chat/test_inputs/existing_yaml_long.yaml", "workflow_chat/test_inputs/history_gen_yaml_long.json", None),
]


@pytest.fixture
def workflow_tester():
    """Pytest fixture to provide the tester instance."""
    return WorkflowChatTester()


@pytest.mark.parametrize("yaml_file,history_file,error_message", TEST_CASES)
def test_workflow_chat_response(workflow_tester, yaml_file, history_file, error_message):
    """
    Test workflow_chat service with various inputs.
    This is a 'show output' test - we run the service and save results for manual review.
    """
    # Create test name for output files
    yaml_name = Path(yaml_file).stem
    history_name = Path(history_file).stem
    test_name = f"{yaml_name}_{history_name}"
    if error_message:
        test_name += "_errors"
    
    print(f"\n{'='*80}")
    print(f"TEST: {yaml_file} + {history_file}")
    if error_message:
        print(f"  With errors: {error_message}")
    print('='*80)
    
    # Create service input
    service_input = workflow_tester.create_service_input(yaml_file, history_file, error_message)
    
    # Call the service
    response = workflow_tester.call_workflow_chat_service(service_input)
    
    # Save response for manual review
    workflow_tester.save_response(response, test_name)
    
    # Print detailed response like original script
    workflow_tester.print_response_details(response, test_name)
    
    # Basic sanity checks (these always pass unless something is very wrong)
    assert response is not None, "Service should return a response"
    assert isinstance(response, dict), "Response should be a dictionary"
    
    print(f"\n✅ Test completed: {test_name}")
    print("-" * 80)


# Example of how you'd add deterministic pass/fail tests later
@pytest.mark.parametrize("yaml_file,history_file,expected_substring", [
    # Add these when you're ready for pass/fail tests
    # ("test_inputs/some_specific.yaml", "test_inputs/some_specific.json", "expected_text"),
])
def test_workflow_chat_deterministic(workflow_tester, yaml_file, history_file, expected_substring):
    """
    Deterministic pass/fail tests for specific expected outputs.
    """
    service_input = workflow_tester.create_service_input(yaml_file, history_file)
    response = workflow_tester.call_workflow_chat_service(service_input)
    
    # Example deterministic check
    assert "response" in response, "Response should contain 'response' key"
    response_text = response["response"]
    assert expected_substring in response_text, f"Response should contain '{expected_substring}'"


if __name__ == "__main__":
    # This allows running the file directly like your current setup
    pytest.main([__file__, "-v"])
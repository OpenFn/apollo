import pytest
import json
import os
from pathlib import Path
from entry import call

def test_echo_service():
    # Setup test paths
    input_path = "tmp/test_input.json"
    output_path = "tmp/test_output.json"
    test_data = {"test": "data"}
    
    # Ensure tmp directory exists
    Path("tmp").mkdir(exist_ok=True)
    
    # Write test input
    with open(input_path, "w") as f:
        json.dump(test_data, f)
    
    try:
        # Call echo service with named arguments
        result = call(
            service="echo",
            input_path=input_path,
            output_path=output_path
        )
        
        # Verify result
        assert result == test_data
        
        # Verify output file
        with open(output_path, "r") as f:
            output_data = json.load(f)
        assert output_data == test_data
        
    finally:
        # Cleanup
        for file in [input_path, output_path]:
            if os.path.exists(file):
                os.remove(file)

def test_error_handling():
    input_path = "tmp/test_input.json"
    output_path = "tmp/test_output.json"
    
    # Write invalid JSON
    with open(input_path, "w") as f:
        f.write("invalid json")
    
    try:
        result = call(
            service="non_existent_service",
            input_path=input_path,
            output_path=output_path
        )
        assert result["type"] == "INTERNAL_ERROR"
        assert result["code"] == 500
    finally:
        # Cleanup
        for file in [input_path, output_path]:
            if os.path.exists(file):
                os.remove(file) 
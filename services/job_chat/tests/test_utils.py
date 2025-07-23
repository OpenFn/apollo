import json
import sys
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any


def call_job_chat_service(service_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call the job_chat service with the given input and return the response.
    
    Args:
        service_input: Dictionary with content, history, context, and optional meta/api_key
        
    Returns:
        The service response as a dictionary
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_input:
        json.dump(service_input, temp_input, indent=2)
        temp_input_path = temp_input.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_output:
        temp_output_path = temp_output.name
    try:
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent.parent / "entry.py"),
            "job_chat",
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
        import os
        try:
            os.unlink(temp_input_path)
            os.unlink(temp_output_path)
        except:
            pass


def make_service_input(history=None, content=None, context=None, meta=None, api_key=None):
    """
    Create a properly formatted input payload for the job_chat service.
    
    Args:
        history: Chat history as a list of {role, content} objects
        content: The user's question or message
        context: Context object containing expression, adaptor, input, output, log
        meta: Additional metadata
        api_key: Optional API key for the model
        
    Returns:
        A dictionary ready to be sent to the job_chat service
    """
    service_input = {
        "history": history or []
    }
    
    if content is not None:
        service_input["content"] = content
        
    if context is not None:
        service_input["context"] = context
    
    if meta is not None:
        service_input["meta"] = meta
        
    if api_key is not None:
        service_input["api_key"] = api_key
        
    return service_input


def print_response_details(response: Dict[str, Any], test_name: str, content: Optional[str] = None):
    """
    Print detailed response information for a job_chat service call.
    
    Args:
        response: The service response object
        test_name: Name of the test (for debugging)
        content: Original user query/content
    """
    print(f"\n===== TEST: {test_name} =====")
    
    if content is not None:
        print("\nUSER CONTENT:")
        print(content)
        
    if "response" in response and isinstance(response["response"], dict):
        if "response" in response["response"]:
            print("\nTEXT RESPONSE:")
            print(response["response"]["response"])
            
        if "suggested_code" in response["response"]:
            print("\nSUGGESTED CODE:")
            print(response["response"]["suggested_code"])
    elif "response" in response:
        print("\nRESPONSE:")
        print(json.dumps(response["response"], indent=2))
        
    if "history" in response:
        print("\nUPDATED HISTORY LENGTH:")
        print(len(response["history"]))
        
    if "usage" in response:
        print("\nTOKEN USAGE:")
        print(json.dumps(response["usage"], indent=2))
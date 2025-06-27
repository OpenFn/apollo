import json
import sys
import yaml
import tempfile
import subprocess
from pathlib import Path
import difflib
from typing import List


def path_matches(path, allowed_paths):
    """Check if a path (list of keys) matches any allowed path pattern."""
    for allowed in allowed_paths:
        allowed_parts = allowed.split('.')
        if len(path) != len(allowed_parts):
            continue
        match = True
        for p, a in zip(path, allowed_parts):
            if a == '*':
                continue
            if p != a:
                match = False
                break
        if match:
            return True
    return False


def assert_yaml_equal_except(orig, new, allowed_paths: List[str], context=''):
    """
    Assert that two YAML objects are equal except for allowed paths.
    allowed_paths: e.g. ['triggers', 'jobs.*.body']
    """
    def compare(o, n, path):
        if path_matches(path, allowed_paths):
            return  # allowed to differ
        if type(o) != type(n):
            raise AssertionError(f"Type mismatch at {'.'.join(path)}: {type(o)} != {type(n)}")
        if isinstance(o, dict):
            for k in set(o.keys()).union(n.keys()):
                if k not in o or k not in n:
                    raise AssertionError(f"Key '{k}' missing at {'.'.join(path)}")
                compare(o[k], n[k], path + [k])
        elif isinstance(o, list):
            if len(o) != len(n):
                raise AssertionError(f"List length mismatch at {'.'.join(path)}: {len(o)} != {len(n)}")
            for i, (oi, ni) in enumerate(zip(o, n)):
                compare(oi, ni, path + [str(i)])
        else:
            if o != n:
                diff = "\n".join(difflib.unified_diff(
                    [str(o)], [str(n)],
                    fromfile='original', tofile='response', lineterm=''
                ))
                raise AssertionError(f"Value mismatch at {'.'.join(path)}:\n{diff}")

    try:
        compare(orig, new, [])
    except AssertionError as e:
        orig_str = yaml.dump(orig, sort_keys=True)
        new_str = yaml.dump(new, sort_keys=True)
        diff = "\n".join(difflib.unified_diff(
            orig_str.splitlines(), new_str.splitlines(),
            fromfile='original', tofile='response', lineterm=''
        ))
        raise AssertionError(f"{context}\n{e}\nFull YAML diff:\n{diff}")


def call_workflow_chat_service(service_input):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_input:
        json.dump(service_input, temp_input, indent=2)
        temp_input_path = temp_input.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_output:
        temp_output_path = temp_output.name
    try:
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "entry.py"),
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
        import os
        try:
            os.unlink(temp_input_path)
            os.unlink(temp_output_path)
        except:
            pass


def make_service_input(existing_yaml, history, content=None, errors=None):
    service_input = {
        "existing_yaml": existing_yaml,
        "history": history
    }
    if content is not None:
        service_input["content"] = content
    if errors is not None:
        service_input["errors"] = errors
    return service_input


def print_response_details(response, test_name):
    """Print detailed response information like the original script."""
    if "response" in response:
        print("\n📝 WORKFLOW_CHAT RESPONSE:")
        print(json.dumps(response["response"], indent=2))
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
    if "usage" in response:
        print("\n📊 TOKEN USAGE:")
        print(json.dumps(response["usage"], indent=2)) 
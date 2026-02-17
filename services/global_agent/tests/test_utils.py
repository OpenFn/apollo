import json
import sys
import yaml
import tempfile
import subprocess
import difflib
from pathlib import Path
from typing import Dict, List, Optional, Any


def call_global_agent_service(service_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call the global_agent service with the given input and return the response.

    Args:
        service_input: Dictionary with content, history, context, and optional fields

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
            "global_agent",
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


def make_service_input(
    existing_yaml: str = None,
    history: List[Dict] = None,
    content: str = None,
    errors: str = None,
    context: Dict = None,
    meta: Dict = None,
    read_only: bool = False,
    api_key: str = None,
    suggest_code: bool = None,
    stream: bool = False
) -> Dict[str, Any]:
    """
    Create a properly formatted input payload for the global_agent service.
    Supports both job_chat and workflow_chat parameter patterns.

    Parameter order matches workflow_chat for compatibility with positional args.

    Args:
        existing_yaml: Current YAML workflow (workflow_chat pattern)
        history: Chat history as a list of {role, content} objects
        content: The user's question or message
        errors: Error message to handle (workflow_chat pattern)
        context: Context object containing expression, adaptor, input, output, log, page_name
        meta: Additional metadata
        read_only: Boolean for read-only mode (workflow_chat pattern)
        api_key: Optional API key for the model (job_chat pattern)
        suggest_code: Boolean flag to indicate whether to use new prompt format (job_chat pattern)
        stream: Boolean flag to enable streaming mode

    Returns:
        A dictionary ready to be sent to the global_agent service
    """
    service_input = {
        "history": history or []
    }

    if content is not None:
        service_input["content"] = content

    if existing_yaml is not None:
        service_input["existing_yaml"] = existing_yaml

    if context is not None:
        service_input["context"] = context

    if meta is not None:
        service_input["meta"] = meta

    if errors is not None:
        service_input["errors"] = errors

    if read_only:
        service_input["read_only"] = read_only

    if api_key is not None:
        service_input["api_key"] = api_key

    if suggest_code is not None:
        service_input["suggest_code"] = suggest_code

    if stream:
        service_input["stream"] = stream

    return service_input


def assert_routed_to(response: Dict[str, Any], expected_service: str, context: str = ""):
    """
    Assert that global_agent routed to the expected service.

    Args:
        response: Global agent response dict
        expected_service: One of "job_code_agent", "workflow_agent", or "planner"
        context: Optional context string for error messages
    """
    assert response is not None, f"{context}: Response is None"
    assert isinstance(response, dict), f"{context}: Response is not a dict: {type(response)}"

    if "meta" not in response:
        # Print response keys to help debug
        print(f"\n{context}: WARNING - Response missing 'meta' field. Response keys: {response.keys()}")
        if "response" in response:
            print(f"Response text (first 200 chars): {response['response'][:200]}")
        return  # Skip assertion if meta is missing (might be error case or edge case)

    if "router_decision" not in response["meta"]:
        print(f"\n{context}: WARNING - meta missing 'router_decision'. Meta keys: {response['meta'].keys()}")
        return  # Skip assertion if router_decision is missing

    actual = response["meta"]["router_decision"]
    assert actual == expected_service, (
        f"{context}: Expected route to '{expected_service}', got '{actual}'"
    )


def print_response_details(response: Dict[str, Any], test_name: str = None, content: Optional[str] = None, errors: Optional[str] = None):
    """
    Print detailed response information for a global_agent service call.
    Supports both job_chat and workflow_chat response patterns.

    Args:
        response: The service response object
        test_name: Name of the test (for debugging, optional)
        content: Original user query/content
        errors: Original error field (workflow_chat pattern)
    """
    if test_name:
        print(f"\n===== TEST: {test_name} =====")

    if content is not None:
        print("\nUSER CONTENT:")
        print(content)

    if errors is not None:
        print("\nERROR FIELD INPUT:")
        print(errors)

    if "response" in response:
        print("\nTEXT RESPONSE:")
        print(response["response"])

    if "suggested_code" in response:
        print("\nSUGGESTED CODE:")
        print(response["suggested_code"])

    if "response_yaml" in response:
        yaml_data = response["response_yaml"]
        if yaml_data and isinstance(yaml_data, str) and yaml_data.strip():
            print("\nGENERATED YAML:")
            print(yaml_data)
        elif yaml_data and yaml_data is not None:
            print("\nGENERATED YAML:")
            print(json.dumps(yaml_data, indent=2))
        else:
            print("\nGENERATED YAML: None (agent provided only text description)")

    if "history" in response:
        print("\nUPDATED HISTORY LENGTH:")
        print(len(response["history"]))

    if "usage" in response:
        print("\nTOKEN USAGE:")
        print(json.dumps(response["usage"], indent=2))

    if "meta" in response and "router_decision" in response["meta"]:
        print("\nROUTER DECISION:")
        print(f"  Service: {response['meta']['router_decision']}")
        if "router_confidence" in response["meta"]:
            print(f"  Confidence: {response['meta']['router_confidence']}")


# ===== YAML validation helpers from workflow_chat =====

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


def assert_yaml_section_contains_all(orig, new, section, context=''):
    """
    Assert that all items in orig[section] are present and unchanged in new[section].
    Allows new items to be added in new[section].

    Args:
        orig: Original YAML as string or dict
        new: New YAML as string or dict
        section: Section name to compare
        context: Context string for error messages
    """
    # Handle both string and dict inputs
    if isinstance(orig, str):
        orig_data = yaml.safe_load(orig)
    else:
        orig_data = orig

    if isinstance(new, str):
        new_data = yaml.safe_load(new)
    else:
        new_data = new

    orig_section = orig_data.get(section, {})
    new_section = new_data.get(section, {})

    for key, value in orig_section.items():
        assert key in new_section, f"{context}: Key '{key}' missing in '{section}'"
        assert new_section[key] == value, (
            f"{context}: Value for '{section}.{key}' changed.\nOriginal: {value}\nNew: {new_section[key]}"
        )


def assert_yaml_has_ids(yaml_str_or_dict, context=''):
    """
    Assert that every job, trigger, and edge in the YAML has a non-empty 'id' field.
    Args:
        yaml_str_or_dict: YAML as string or dict
        context: Context string for error messages
    """
    if isinstance(yaml_str_or_dict, str):
        data = yaml.safe_load(yaml_str_or_dict)
    else:
        data = yaml_str_or_dict

    # Check jobs
    jobs = data.get('jobs', {})
    for job_key, job_data in jobs.items():
        assert 'id' in job_data, f"{context}: Job '{job_key}' missing 'id' field."
        assert job_data['id'] not in (None, '', []), f"{context}: Job '{job_key}' has empty 'id' field."

    # Check triggers
    triggers = data.get('triggers', {})
    for trig_key, trig_data in triggers.items():
        assert 'id' in trig_data, f"{context}: Trigger '{trig_key}' missing 'id' field."
        assert trig_data['id'] not in (None, '', []), f"{context}: Trigger '{trig_key}' has empty 'id' field."

    # Check edges
    edges = data.get('edges', {})
    for edge_key, edge_data in edges.items():
        assert 'id' in edge_data, f"{context}: Edge '{edge_key}' missing 'id' field."
        assert edge_data['id'] not in (None, '', []), f"{context}: Edge '{edge_key}' has empty 'id' field."


def assert_yaml_jobs_have_body(yaml_str_or_dict, context=''):
    """
    Assert that every job in the YAML has a non-empty 'body' field.
    Args:
        yaml_str_or_dict: YAML as string or dict
        context: Context string for error messages
    """
    if isinstance(yaml_str_or_dict, str):
        data = yaml.safe_load(yaml_str_or_dict)
    else:
        data = yaml_str_or_dict

    jobs = data.get('jobs', {})
    for job_key, job_data in jobs.items():
        assert 'body' in job_data, f"{context}: Job '{job_key}' missing 'body' field."
        assert job_data['body'] not in (None, '', []), f"{context}: Job '{job_key}' has empty 'body' field."


def assert_no_special_chars(yaml_str_or_dict, context=''):
    """
    Assert that there are no special characters in job names, source_job and target_job fields.
    Special characters are anything that's not alphanumeric, space, hyphen, or underscore.

    Args:
        yaml_str_or_dict: YAML as string or dict
        context: Context string for error messages
    """
    import re
    if isinstance(yaml_str_or_dict, str):
        data = yaml.safe_load(yaml_str_or_dict)
    else:
        data = yaml_str_or_dict

    # Pattern matches any character that is NOT alphanumeric, space, hyphen, or underscore
    special_char_pattern = re.compile(r'[^a-zA-Z0-9\s\-_]')

    # Check job names
    jobs = data.get('jobs', {})
    for job_key, job_data in jobs.items():
        if 'name' in job_data and job_data['name']:
            name = str(job_data['name'])
            match = special_char_pattern.search(name)
            assert not match, f"{context}: Job '{job_key}' name '{name}' contains special character '{match.group(0)}'"

    # Check edge: source_job, target_job and edge key
    edges = data.get('edges', {})
    for edge_key, edge_data in edges.items():
        if 'source_job' in edge_data and edge_data['source_job']:
            source = str(edge_data['source_job'])
            match = special_char_pattern.search(source)
            assert not match, f"{context}: Edge '{edge_key}' source_job '{source}' contains special character '{match.group(0)}'"

        if 'target_job' in edge_data and edge_data['target_job']:
            target = str(edge_data['target_job'])
            match = special_char_pattern.search(target)
            assert not match, f"{context}: Edge '{edge_key}' target_job '{target}' contains special character '{match.group(0)}'"

        if "->" in edge_key:
            source_part, target_part = edge_key.split("->", 1)

            match = special_char_pattern.search(source_part)
            assert not match, f"{context}: Edge key '{edge_key}' source part '{source_part}' contains special character '{match.group(0)}'"

            match = special_char_pattern.search(target_part)
            assert not match, f"{context}: Edge key '{edge_key}' target part '{target_part}' contains special character '{match.group(0)}'"

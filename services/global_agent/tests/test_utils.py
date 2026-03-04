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
    stream: bool = False,
    page: str = None,
) -> Dict[str, Any]:
    """
    Build a global_agent input payload.

    For workflow editing: pass existing_yaml with the full YAML.
    For job code editing: pass context with expression/adaptor/page_name fields,
    which are wrapped into a minimal workflow YAML automatically.

    Args:
        existing_yaml: Full workflow YAML (used as-is for workflow tests)
        history: Chat history as a list of {role, content} objects
        content: The user's question or message
        errors: Error message (used as content if content is not provided)
        context: Job code context with expression, adaptor, page_name fields
        meta: Ignored (no longer part of the payload)
        read_only: Ignored (no longer part of the payload)
        api_key: Optional API key for the model
        suggest_code: Ignored (routing is automatic)
        stream: Enable streaming mode
        page: Explicit page URL override

    Returns:
        A dictionary ready to be sent to the global_agent service
    """
    service_input = {
        "content": content or errors or "",
        "history": history or []
    }

    if existing_yaml is not None and str(existing_yaml).strip():
        service_input["workflow_yaml"] = existing_yaml
    elif context and any(k in context for k in ["expression", "adaptor"]):
        # Wrap job context into a minimal workflow YAML so the router can extract it
        job_key = "test-job"
        job_entry = {}
        if context.get("adaptor"):
            job_entry["adaptor"] = context["adaptor"]
        if context.get("page_name"):
            job_entry["name"] = context["page_name"]
        if context.get("expression") is not None:
            job_entry["body"] = context["expression"]

        minimal_yaml = {"name": "test", "jobs": {job_key: job_entry}}
        service_input["workflow_yaml"] = yaml.dump(minimal_yaml, sort_keys=False)

        if page is None:
            page = f"workflows/test/{job_key}"

    if page is not None:
        service_input["page"] = page

    if api_key is not None:
        service_input["api_key"] = api_key

    if stream:
        service_input["options"] = {"stream": True}

    return service_input


def _extract_job_body(workflow_yaml: Optional[str], job_key: str) -> Optional[str]:
    """Extract a job's body from a workflow YAML string by job key."""
    if not workflow_yaml:
        return None
    try:
        data = yaml.safe_load(workflow_yaml)
        return data.get("jobs", {}).get(job_key, {}).get("body")
    except Exception:
        return None


def get_attachment(response: Dict[str, Any], attachment_type: str) -> Optional[str]:
    """
    Extract an artifact from the response by type.

    workflow_yaml: returned directly from response["workflow_yaml"]
    job_code: extracted from the "test-job" body in workflow_yaml (set by make_service_input)
    """
    if attachment_type == "workflow_yaml":
        return response.get("workflow_yaml")
    elif attachment_type == "job_code":
        return _extract_job_body(response.get("workflow_yaml"), "test-job")
    return None


def get_response_yaml(response: Dict[str, Any]) -> Optional[str]:
    """Extract workflow YAML from response."""
    return response.get("workflow_yaml")


def get_suggested_code(response: Dict[str, Any]) -> Optional[str]:
    """Extract suggested job code from workflow YAML (test-job body)."""
    return _extract_job_body(response.get("workflow_yaml"), "test-job")


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
        print(f"\n{context}: WARNING - Response missing 'meta' field. Response keys: {response.keys()}")
        if "response" in response:
            print(f"Response text (first 200 chars): {response['response'][:200]}")
        return

    meta = response["meta"]
    if "agents" not in meta:
        print(f"\n{context}: WARNING - meta missing 'agents'. Meta keys: {meta.keys()}")
        return

    agents = meta["agents"]
    assert expected_service in agents, (
        f"{context}: Expected '{expected_service}' in agents list, got {agents}"
    )


def print_response_details(response: Dict[str, Any], test_name: str = None, content: Optional[str] = None, errors: Optional[str] = None):
    """
    Print detailed response information for a global_agent service call.

    Args:
        response: The service response object
        test_name: Name of the test (for debugging, optional)
        content: Original user query/content
        errors: Unused, kept for backwards compatibility
    """
    if test_name:
        print(f"\n===== TEST: {test_name} =====")

    if content is not None:
        print("\nUSER CONTENT:")
        print(content)

    if "response" in response:
        print("\nTEXT RESPONSE:")
        print(response["response"])

    if "workflow_yaml" in response and response["workflow_yaml"]:
        print("\nWORKFLOW YAML:")
        print(response["workflow_yaml"])

    if "history" in response:
        print("\nUPDATED HISTORY LENGTH:")
        print(len(response["history"]))

    if "usage" in response:
        print("\nTOKEN USAGE:")
        print(json.dumps(response["usage"], indent=2))

    if "meta" in response:
        print("\nEXECUTION META:")
        if "agents" in response["meta"]:
            print(f"  Agents: {' -> '.join(response['meta']['agents'])}")
        if "router_confidence" in response["meta"]:
            print(f"  Router Confidence: {response['meta']['router_confidence']}")
        if "planner_iterations" in response["meta"]:
            print(f"  Planner Iterations: {response['meta']['planner_iterations']}")


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

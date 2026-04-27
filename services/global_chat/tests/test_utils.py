import json
import sys
import yaml
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any

# YAML helpers live in `testing.yaml_assertions`; re-exported so existing
# imports from this module keep working. New code should import directly.
from testing.yaml_assertions import (  # noqa: F401
    assert_no_special_chars,
    assert_yaml_equal_except,
    assert_yaml_has_ids,
    assert_yaml_jobs_have_body,
    assert_yaml_section_contains_all,
    path_matches,
)


def call_global_chat_service(service_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call the global_chat service with the given input and return the response.

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
            "global_chat",
            "--input", temp_input_path,
            "--output", temp_output_path
        ]
        print(cmd)
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        if result.returncode != 0:
            raise Exception(f"Service call failed: {result.stderr}")
        with open(temp_output_path, 'r') as f:
            print (f)
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
    Build a global_chat input payload.

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
        A dictionary ready to be sent to the global_chat service
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


def _find_attachment(response: Dict[str, Any], attachment_type: str) -> Optional[str]:
    """Find an attachment by type in the response attachments list."""
    for att in response.get("attachments", []):
        if att.get("type") == attachment_type:
            return att.get("content")
    return None


def get_attachment(response: Dict[str, Any], attachment_type: str) -> Optional[str]:
    """
    Extract an artifact from the response by type.

    workflow_yaml: found in the attachments list with type "workflow_yaml"
    job_code: extracted from the "test-job" body in the workflow_yaml attachment (set by make_service_input)
    """
    if attachment_type == "workflow_yaml":
        return _find_attachment(response, "workflow_yaml")
    elif attachment_type == "job_code":
        yaml_content = _find_attachment(response, "workflow_yaml")
        return _extract_job_body(yaml_content, "test-job")
    return None


def get_response_yaml(response: Dict[str, Any]) -> Optional[str]:
    """Extract workflow YAML from response attachments."""
    return _find_attachment(response, "workflow_yaml")


def get_suggested_code(response: Dict[str, Any]) -> Optional[str]:
    """Extract suggested job code from workflow YAML attachment (test-job body)."""
    yaml_content = _find_attachment(response, "workflow_yaml")
    return _extract_job_body(yaml_content, "test-job")


def assert_routed_to(response: Dict[str, Any], expected_service: str, context: str = ""):
    """
    Assert that global_chat routed to the expected service.

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
    Print detailed response information for a global_chat service call.

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

    workflow_yaml = _find_attachment(response, "workflow_yaml") if "attachments" in response else None
    if workflow_yaml:
        print("\nWORKFLOW YAML:")
        print(workflow_yaml)

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
        if "tool_calls" in response["meta"] and response["meta"]["tool_calls"]:
            print("\nPLANNER TOOL CALLS:")
            for i, call in enumerate(response["meta"]["tool_calls"], 1):
                tool = call.get("tool", "unknown")
                inp = call.get("input", {})
                msg = inp.get("message", "")
                job_key = inp.get("job_key", "")
                skipped = call.get("skipped", False)
                label = f"{tool} [SKIPPED]" if skipped else tool
                print(f"\n  --- Step {i}: {label} ---")
                if job_key:
                    print(f"  job_key: {job_key}")
                print(f"  message:\n    {msg.strip().replace(chr(10), chr(10) + '    ')}")


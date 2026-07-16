"""
Shared utility functions for working with workflow YAML strings.

Used by global_chat (router, planner, subagent caller) and by job_chat in
subagent mode for job extraction, code stitching, and step inspection.
"""
import re

import yaml


def get_step_name_from_page(page: str | None) -> str | None:
    """
    Extract step name from page URL.

    Examples:
      workflows/my-workflow/fetch-patients -> "fetch-patients"
      workflows/my-workflow                -> None
      workflows/my-workflow/settings       -> None
    """
    if not page:
        return None

    parts = page.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "workflows" and parts[2] != "settings":
        return parts[2]

    return None


def normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching: lowercase, non-alphanumeric chars become hyphens."""
    return re.sub(r'[^a-z0-9]', '-', name.lower()).strip('-')


def find_job_in_yaml(yaml_str: str, step_name: str) -> tuple[str | None, dict | None]:
    """
    Find a job in the workflow YAML by step name.

    Tries direct key match first, then normalized name comparison against
    both the job key and the job's name field.

    Returns:
        (job_key, job_data) or (None, None) if not found or on parse error
    """
    try:
        yaml_data = yaml.safe_load(yaml_str)
    except Exception:
        return None, None

    if not yaml_data or "jobs" not in yaml_data:
        return None, None

    jobs = yaml_data["jobs"]

    # Direct key match
    if step_name in jobs:
        return step_name, jobs[step_name]

    # Normalized match: compare against job key and name field
    normalized_step = normalize_name(step_name)
    for job_key, job_data in jobs.items():
        if normalize_name(job_key) == normalized_step:
            return job_key, job_data
        job_name = job_data.get("name", "")
        if normalize_name(job_name) == normalized_step:
            return job_key, job_data

    return None, None


EMPTY_JOB_BODY = "// Add operations here"


def workflow_has_job_code(yaml_str: str | None) -> bool:
    """Return True if any job has a non-empty, non-placeholder body.

    The canonical empty-job marker is ``// Add operations here`` (see
    workflow_chat); a blank body or that marker means "no code yet". Used to
    decide whether a "what does this do" question needs the planner (to read the
    real code) or can take the faster workflow_agent path (structure only).
    """
    try:
        yaml_data = yaml.safe_load(yaml_str)
    except Exception:
        return False
    if not yaml_data or "jobs" not in yaml_data:
        return False
    for job_data in yaml_data["jobs"].values():
        body = (job_data or {}).get("body")
        if isinstance(body, str) and body.strip() and body.strip() != EMPTY_JOB_BODY:
            return True
    return False


def redact_job_bodies(yaml_str: str) -> str:
    """Return workflow YAML with job bodies replaced by a placeholder."""
    try:
        yaml_data = yaml.safe_load(yaml_str)
        if yaml_data and "jobs" in yaml_data:
            for job_data in yaml_data["jobs"].values():
                if "body" in job_data:
                    job_data["body"] = "# [use inspect_job_code to view]"
            return yaml.dump(yaml_data, sort_keys=False)
    except Exception:
        pass
    return yaml_str


def stitch_job_code(yaml_str: str, job_key: str, new_code: str) -> str:
    """
    Replace a job's body in the workflow YAML with new code.

    Returns the original YAML string unchanged if parsing or stitching fails.
    """
    try:
        yaml_data = yaml.safe_load(yaml_str)
        if yaml_data and "jobs" in yaml_data and job_key in yaml_data["jobs"]:
            yaml_data["jobs"][job_key]["body"] = new_code
            return yaml.dump(yaml_data, sort_keys=False)
    except Exception:
        pass

    return yaml_str


# Read-only step inspection, shared by the planner and job_chat (subagent
# mode) so both agents explore the workflow with the exact same tool.

INSPECT_JOB_CODE_TOOL = {
    "name": "inspect_job_code",
    "description": """Read the current code body of one or more jobs in the workflow (read-only).

Use this to inspect existing step code before editing — e.g. to find which steps a change applies to before editing only those, or to base one step on another. Pass all the job keys you need in a single call rather than calling once per job.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "job_keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The job keys to inspect (e.g. ['fetch-patients', 'load-dhis2'])",
            },
        },
        "required": ["job_keys"],
    },
}


def inspect_job_code(yaml_str: str | None, job_keys: list[str]) -> str:
    """Execute the inspect_job_code tool: return the named jobs' code bodies."""
    if not yaml_str:
        return "No workflow available to inspect."
    if not job_keys:
        return "ERROR: No job keys provided."

    parts = []
    for job_key in job_keys:
        _, job_data = find_job_in_yaml(yaml_str, job_key)
        if job_data and job_data.get("body"):
            parts.append(f"Job code for '{job_key}':\n\n{job_data['body']}")
        else:
            parts.append(f"No code found for job '{job_key}'.")
    return "\n\n".join(parts)

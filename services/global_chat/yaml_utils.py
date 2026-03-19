"""
Shared YAML utility functions for working with workflow YAML strings.

Used by router and subagent caller for job extraction and code stitching.
"""
import re
import yaml
from typing import Dict, Optional, Tuple


def get_step_name_from_page(page: Optional[str]) -> Optional[str]:
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


def find_job_in_yaml(yaml_str: str, step_name: str) -> Tuple[Optional[str], Optional[Dict]]:
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

"""
Shared utility functions for working with workflow YAML strings.

Used by global_chat (router, planner, subagent caller) and by job_chat in
subagent mode for job extraction, code stitching, and step inspection.
"""

import yaml
from name_rules import normalize_for_lookup
from util import create_logger

logger = create_logger("yaml_utils")


def get_page_view(page: str | None) -> tuple[str | None, str | None]:
    """
    Classify what the user has on screen from the `page` breadcrumb — the single
    parser for that URL (get_step_name_from_page delegates to this).

    Shapes (names are raw, may contain spaces):
      workflows/<workflow>/<job>  -> ("step", "<job>")     job code page
      workflows/<workflow>        -> ("overview", None)     workflow canvas
      settings / absent / anything else -> (None, None)

    A step name may itself contain "/", so everything after the workflow
    segment is taken as the step name rather than just the third segment —
    otherwise "workflows/wf/Import A/B" loses the step focus entirely. The
    split between workflow and step is still a guess when the *workflow* name
    contains a "/", so the returned step name is a best-effort candidate: the
    caller must validate it against the workflow YAML rather than trust it.
    """
    if not page:
        return None, None
    parts = page.strip("/").split("/")
    if parts[0] != "workflows" or len(parts) < 2:
        return None, None
    if len(parts) == 2:
        return "overview", None
    step = "/".join(parts[2:])
    if step == "settings":
        return None, None
    return "step", step


def get_step_name_from_page(page: str | None) -> str | None:
    """
    Extract the focused step name from a job-code page URL, or None for the
    canvas, settings, or an unrecognized value.

    Examples:
      workflows/my-workflow/fetch-patients -> "fetch-patients"
      workflows/my-workflow                -> None
      workflows/my-workflow/settings       -> None
    """
    view, step = get_page_view(page)
    return step if view == "step" else None


def normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching: lowercase, non-alphanumeric chars become hyphens.

    Unicode-aware — see ``name_rules.normalize_for_lookup``. "Alphanumeric"
    means a letter, mark or digit in any script, so a non-Latin name folds to
    itself rather than to the empty string.
    """
    return normalize_for_lookup(name)


def find_job_in_yaml(yaml_str: str, step_name: str) -> tuple[str | None, dict | None]:
    """
    Find a job in the workflow YAML by step name.

    Resolution order, strictest first: an exact key, an exact name, then the
    normalized fold — and the fold resolves only when it picks out exactly one
    job. Anything ambiguous returns (None, None).

    The order matters because the result is *written* to: `router` and
    `planner` hand the key straight to `stitch_job_code`, which replaces that
    step's body. Taking the first fold hit meant an earlier job's *key* fold
    could beat a later job's *exact name* — steps keyed `upload-data`
    ("Legacy uploader") and `upload-data-2` ("Upload Data"), a lookup for
    "Upload Data", and the model's generated code landed on the legacy step.
    A miss costs a retry; a wrong hit destroys work.

    Returns:
        (job_key, job_data) or (None, None) if not found, ambiguous, or on
        parse error
    """
    try:
        yaml_data = yaml.safe_load(yaml_str)
    except Exception:
        return None, None

    if not isinstance(yaml_data, dict) or not isinstance(yaml_data.get("jobs"), dict):
        return None, None

    jobs = yaml_data["jobs"]

    if step_name in jobs:
        return step_name, jobs[step_name]

    exact_names = [
        key for key, data in jobs.items() if (data or {}).get("name") == step_name
    ]
    if exact_names:
        return _only_match(exact_names, jobs, step_name, "name")

    # An empty normalization carries no information (the name was all
    # punctuation), so never match on it.
    normalized_step = normalize_name(step_name)
    if not normalized_step:
        return None, None

    folded = [
        key
        for key, data in jobs.items()
        if normalize_name(key) == normalized_step
        or ((data or {}).get("name") and normalize_name(data["name"]) == normalized_step)
    ]
    return _only_match(folded, jobs, step_name, "folded name")


def _only_match(
    matches: list, jobs: dict, step_name: str, how: str,
) -> tuple[str | None, dict | None]:
    """Return the single match, or nothing when more than one job qualifies."""
    if len(matches) == 1:
        return matches[0], jobs[matches[0]]
    logger.warning(
        f"Step reference {step_name!r} matches the {how} of {len(matches)} jobs "
        f"({', '.join(sorted(str(match) for match in matches))}); leaving it "
        f"unresolved rather than guessing, because the caller writes to it",
    )
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
    """Return workflow YAML with job bodies replaced by a placeholder and id
    fields removed.

    This is the read-only structural view shown to the planner and to job_chat
    in subagent mode. It never round-trips back into a real workflow, so the
    UUID ids are pure noise to the model — dropping them saves tokens.
    """
    try:
        yaml_data = yaml.safe_load(yaml_str)
        if yaml_data and "jobs" in yaml_data:
            _remove_ids(yaml_data)
            for job_data in yaml_data["jobs"].values():
                if "body" in job_data:
                    job_data["body"] = "# [use inspect_job_code to view]"
            return yaml.dump(yaml_data, sort_keys=False)
    except Exception:
        pass
    return yaml_str


def _remove_ids(obj: object) -> None:
    """Recursively remove 'id' keys from a parsed YAML structure."""
    if isinstance(obj, dict):
        obj.pop("id", None)
        for value in obj.values():
            _remove_ids(value)
    elif isinstance(obj, list):
        for item in obj:
            _remove_ids(item)


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

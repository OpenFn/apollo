"""
Shared utility functions for working with workflow YAML strings.

Used by global_chat (router, planner, subagent caller) and by job_chat in
subagent mode for job extraction, code stitching, and step inspection.
"""
from collections.abc import Iterator

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
    if not isinstance(yaml_data, dict) or not isinstance(yaml_data.get("jobs"), dict):
        return False
    for job_data in yaml_data["jobs"].values():
        body = (job_data or {}).get("body")
        if isinstance(body, str) and body.strip() and body.strip() != EMPTY_JOB_BODY:
            return True
    return False


#: What the model is told when the workflow cannot be safely redacted. Without
#: it the model gets an empty structure and reads it as "this workflow has no
#: steps", which is a different and worse lie than "I cannot show you this".
WITHHELD_NOTICE = (
    "# The workflow could not be prepared for display and has been withheld.\n"
    "# Do not conclude that it is empty or has no steps. Ask the user to\n"
    "# describe what they need, or use inspect_job_code to read a named step.\n"
)

REDACTED_BODY = "# [use inspect_job_code to view]"

BODY_KEY = "body"


def iter_key_holders(node: object, key: str) -> "Iterator[dict]":
    """Yield every mapping in the document that carries `key`.

    THE tree walker. Everything that redacts, counts or preserves job bodies
    goes through this one function. Three separate walkers with three different
    reachability profiles is why the same leak kept reappearing in a different
    function each time it was fixed: each site had its own idea of where a body
    could live, and a document shape only had to escape one of them.

    Walks dicts, lists, tuples and sets, so an `!!omap` or an `!!set` cannot
    carry a body past it, and tracks visited containers so a YAML alias or a
    self-referential anchor terminates.
    """
    seen: set[int] = set()

    def walk(current: object) -> "Iterator[dict]":
        if isinstance(current, dict):
            if id(current) in seen:
                return
            seen.add(id(current))
            if key in current:
                yield current
            for value in current.values():
                yield from walk(value)
        elif isinstance(current, (list, tuple, set, frozenset)):
            if id(current) in seen:
                return
            seen.add(id(current))
            for item in current:
                yield from walk(item)

    yield from walk(node)


def iter_body_holders(node: object) -> "Iterator[dict]":
    """Yield every mapping in the document that carries a `body` key."""
    yield from iter_key_holders(node, BODY_KEY)


def iter_id_holders(node: object) -> "Iterator[dict]":
    """Yield every mapping in the document that carries an `id` key.

    Separate from the body walker on purpose: an id check must look at ids and
    not at bodies, because `const __ID_FIELD = state.data.id;` is ordinary job
    code and a substring search over the whole document flags it.
    """
    yield from iter_key_holders(node, "id")


#: The swap token workflow_chat puts in place of a real body before sending the
#: document to the model. Not job code, so it counts as redacted here.
CODE_PLACEHOLDER_PREFIX = "__CODE_BLOCK_"


def is_code_placeholder(value: object) -> bool:
    """True if `value` is one of our own body swap tokens."""
    return (
        isinstance(value, str)
        and value.startswith(CODE_PLACEHOLDER_PREFIX)
        and value.endswith("__")
    )


def _is_redacted(body: object) -> bool:
    """True if `body` holds nothing that needs keeping from the model."""
    if body is None:
        return True
    if isinstance(body, str):
        stripped = body.strip()
        return (
            not stripped
            or stripped in (REDACTED_BODY, EMPTY_JOB_BODY)
            or is_code_placeholder(stripped)
        )
    # A non-string body — a dict, a list, a number, !!binary. Never assume it is
    # harmless: gating on `isinstance(body, str)` is what let `body: [SECRET]`
    # through both the redactor and the check meant to catch what it skipped.
    return False


def has_unredacted_body(node: object) -> bool:
    """True if any `body` anywhere still holds content."""
    return any(not _is_redacted(holder[BODY_KEY]) for holder in iter_body_holders(node))


def redact_job_bodies(yaml_str: str) -> str:  # noqa: PLR0911 - one return per way this can refuse
    """Return workflow YAML with job bodies replaced by a placeholder and id
    fields removed.

    This is the read-only structural view shown to the planner and to job_chat
    in subagent mode. It never round-trips back into a real workflow, so the
    UUID ids are pure noise to the model — dropping them saves tokens.

    Never returns its input. The input is the unredacted document, so every
    `return yaml_str` is a leak waiting for a document shape that skips the
    redaction above it. The output is always a re-serialisation of a structure
    this function has walked, or the withheld notice.
    """
    try:
        yaml_data = yaml.safe_load(yaml_str)
    except Exception as error:
        # Deliberately not `logger.exception`: PyYAML puts the offending
        # document text in the error's mark, and a traceback carries it into
        # Sentry via `exc_text`, which the log mask never rewrites.
        logger.warning(f"Could not parse workflow YAML to redact job bodies ({type(error).__name__})")
        return WITHHELD_NOTICE

    if yaml_data is None or yaml_data == {}:
        # No data at all — a comment-only or empty document. Nothing to leak
        # and nothing to say.
        return ""

    if not isinstance(yaml_data, dict):
        # A workflow is a mapping. `workflow_yaml` is an unvalidated client
        # string, and a top-level scalar or a sequence of strings has no `body`
        # key for the walker to find — so it would sail through the redaction
        # below untouched and be handed back whole, secrets and all. Withhold
        # anything that is not a shape this function walks.
        logger.warning(
            f"Workflow YAML is a {type(yaml_data).__name__}, not a mapping; withholding it",
        )
        return WITHHELD_NOTICE

    try:
        for holder in iter_body_holders(yaml_data):
            holder[BODY_KEY] = REDACTED_BODY
        leftover = has_unredacted_body(yaml_data)
    except Exception as error:
        logger.error(f"Redaction failed ({type(error).__name__}); withholding the workflow")
        return WITHHELD_NOTICE

    if leftover:  # pragma: no cover - the walker above should make this impossible
        logger.warning("A job body survived redaction; withholding the workflow")
        return WITHHELD_NOTICE

    try:
        remove_ids(yaml_data)
        return yaml.dump(yaml_data, sort_keys=False, allow_unicode=True)
    except Exception as error:
        logger.error(f"Could not re-serialise the redacted workflow ({type(error).__name__})")
        return WITHHELD_NOTICE


def remove_ids(node: object) -> None:
    """Recursively remove 'id' keys from a parsed YAML structure.

    Same container types and same cycle guard as `iter_body_holders`. The
    guard is not cosmetic: YAML aliases let a small document expand
    enormously, and a walker without a visited set re-walks every expansion.
    Eight levels of nine-way alias expansion is 400 bytes on the wire and
    nine-to-the-eighth node visits without it.
    """
    seen: set[int] = set()

    def walk(current: object) -> None:
        if isinstance(current, dict):
            if id(current) in seen:
                return
            seen.add(id(current))
            current.pop("id", None)
            for value in current.values():
                walk(value)
        elif isinstance(current, (list, tuple, set, frozenset)):
            if id(current) in seen:
                return
            seen.add(id(current))
            for item in current:
                walk(item)

    walk(node)


#: Kept for the private name this used to have.
_remove_ids = remove_ids


def stitch_job_code(yaml_str: str, job_key: str, new_code: str) -> str:
    """
    Replace a job's body in the workflow YAML with new code.

    Returns the original YAML string unchanged if parsing or stitching fails.
    """
    try:
        yaml_data = yaml.safe_load(yaml_str)
        jobs = yaml_data.get("jobs") if isinstance(yaml_data, dict) else None
        if isinstance(jobs, dict) and isinstance(jobs.get(job_key), dict):
            jobs[job_key]["body"] = new_code
            return yaml.dump(yaml_data, sort_keys=False, allow_unicode=True)
        logger.error(
            f"Could not stitch job code: no job keyed '{job_key}' in the workflow. "
            f"The generated code has been discarded.",
        )
    except Exception as error:
        # Not `logger.exception`: a PyYAML error mark carries document text.
        logger.error(f"Could not stitch job code into the workflow YAML ({type(error).__name__})")

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

"""Langfuse tracking utilities for controlling trace export and tagging."""
import difflib
import re
from typing import Any

import yaml

# Every field the server may fill in on a payload, not just the one it fills
# in today: a value under one of these belongs to the deployment rather than
# to the caller. langfuse_public_key is deliberately absent - it is meant to
# be visible, and masking it would cost a useful identifier for nothing.
_SECRET_KEY_NAMES = {
    "api_key",
    "anthropic_api_key",
    "openai_api_key",
    "pinecone_api_key",
    "langfuse_secret_key",
    "authorization",
    "x_api_key",
}

# json.loads accepts around a thousand levels of nesting and this runs over
# whatever a caller sends, so a deep payload could otherwise take the process
# down with a RecursionError.
_MAX_DEPTH = 50

# A backstop for a key inside a string, where the name list cannot see it.
# Deliberately narrow: this also passes over workflow YAML, job code and
# service results, so a loose pattern corrupts a caller's own data. Hence a
# known provider prefix, or a run too long and unbroken to be a name.
# test_mask_secrets.py pins both directions.
_SECRET_VALUE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])sk-(?:"
    r"(?:ant|proj|svcacct|lf|or)-[\w-]+"
    r"|[A-Za-z0-9]{20,}"
    r")",
)


def _normalise_name(key: object) -> str:
    return str(key).lower().replace("-", "").replace("_", "")


# Compared in normalised form, so api-key, apiKey and X-Api-Key are all caught
# by the one readable entry above.
_NORMALISED_SECRET_NAMES = {_normalise_name(name) for name in _SECRET_KEY_NAMES}


def _is_secret_name(key: object) -> bool:
    return _normalise_name(key) in _NORMALISED_SECRET_NAMES


#: Payload fields that carry the user's job code or workflow. `mask_secrets`
#: matches credential field names and key-shaped values; it has no notion of
#: job code, so these sail through it untouched.
CODE_BEARING_FIELDS = frozenset({
    "existing_yaml",
    "workflow_yaml",
    "expression",
    "code",
    "old_code",
    "new_code",
    "body",
    "history",
    "content",
    "text_answer",
    "llm_text_answer",
    "llm_edit_answer",
    "suggested_code",
})


#: How deep to recurse before giving up. A cyclic payload is not expected, but
#: this runs on the error path and must not be the thing that raises.
MAX_SCRUB_DEPTH = 6


def drop_code(data: Any, _depth: int = 0) -> Any:  # noqa: ANN401
    """Replace job code and workflow YAML with a size, recursively.

    Used before anything is attached to a Sentry event. Keeping the field name
    and the size preserves everything an operator needs to tell one failure
    from another; keeping the value exports the user's workflow to a third
    party on every captured event, and `set_context` persists on the isolation
    scope, so one chat request would attach its workflow to every later event
    in the process.
    """
    if _depth > MAX_SCRUB_DEPTH:
        # Fail closed. Returning the subtree here hands back whatever it holds,
        # which on a scrubber is the one outcome that must not happen.
        # mask_secrets does the same thing below with [TRUNCATED].
        return "<too deeply nested to scrub, withheld>"
    if isinstance(data, dict):
        scrubbed = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in CODE_BEARING_FIELDS:
                scrubbed[key] = _summarise(value)
            else:
                scrubbed[key] = drop_code(value, _depth + 1)
        return scrubbed
    if isinstance(data, (list, tuple)):
        return type(data)(drop_code(item, _depth + 1) for item in data)
    return data


def _summarise(value: Any) -> str:  # noqa: ANN401
    """Describe a value without reproducing it."""
    if value is None:
        return "<absent>"
    if isinstance(value, str):
        return f"<{len(value)} characters withheld>"
    if isinstance(value, (list, tuple, dict)):
        return f"<{type(value).__name__} of {len(value)} withheld>"
    return f"<{type(value).__name__} withheld>"


def mask_secrets(data: Any, _depth: int = 0) -> Any:  # noqa: ANN401
    """Langfuse mask callback: redact API keys from all traced data.

    Applied by the SDK to every span's input, output and metadata before
    export, so keys passed as function arguments to @observe-decorated
    functions never reach Langfuse. Also used anywhere a service's own output
    could carry a value the server put in the payload.
    """
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"

    if isinstance(data, dict):
        return {
            k: "[REDACTED]"
            if _is_secret_name(k) and v
            else mask_secrets(v, _depth + 1)
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [mask_secrets(v, _depth + 1) for v in data]
    if isinstance(data, str):
        return _SECRET_VALUE_PATTERN.sub("[REDACTED]", data)
    return data


def should_track(data_dict: dict, force: bool = False) -> bool:
    """Check if this session should be tracked in Langfuse."""
    if force:
        return True
    return bool(data_dict.get("metrics_opt_in"))


def build_tags(service_name: str, user_info: dict) -> list:
    """Build Langfuse tags list from service name and user persona."""
    tags = [service_name]
    persona = user_info.get("persona") if user_info else None
    if persona:
        tags.append(persona)
    return tags


class _BlockScalarDumper(yaml.SafeDumper):
    """Dumper that renders multi-line strings (job bodies) as literal blocks
    so embedded code stays line-diffable."""


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_BlockScalarDumper.add_representer(str, _represent_str)


def _normalize_yaml(yaml_str: str) -> str:
    """Re-serialize workflow YAML so both diff sides share one formatting.

    The services round-trip YAML through safe_load/dump, so a raw diff of
    input vs output would flag formatting-only changes (key order, quoting,
    indentation) as generated. Falls back to the raw string if parsing fails.
    """
    try:
        data = yaml.safe_load(yaml_str)
    except Exception:
        return yaml_str
    if not isinstance(data, dict):
        return yaml_str
    return yaml.dump(data, Dumper=_BlockScalarDumper, sort_keys=False, allow_unicode=True)


def build_generation_diff(
    original: str | None, generated: str | None, yaml_mode: bool = False,
) -> dict | None:
    """Build Langfuse trace metadata describing what the model wrote this turn.

    Diffs the pre-existing artifact (job code or workflow YAML) against the
    generated one, so evaluators can tell model output from pre-existing
    (e.g. user-written) content. Returns None when nothing was generated.

    Never raises: this runs inside production request handling, and a
    monitoring failure must degrade to "no diff", not a failed response.
    """
    try:
        if not generated:
            return None

        original = original or ""
        if yaml_mode:
            original = _normalize_yaml(original)
            generated = _normalize_yaml(generated)

        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                generated.splitlines(),
                fromfile="original",
                tofile="generated",
                n=5,
                lineterm="",
            ),
        )
        added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
        return {
            "generation_diff": "\n".join(diff_lines),
            "diff_stats": {"lines_added": added, "lines_removed": removed},
        }
    except Exception as e:
        # print, not create_logger: this must stay out of the user-facing stream
        print(f"build_generation_diff failed, skipping diff metadata ({type(e).__name__})")  # noqa: T201
        return None

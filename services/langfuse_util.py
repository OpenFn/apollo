"""Langfuse tracking utilities for controlling trace export and tagging."""
import difflib

import yaml


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
    return yaml.dump(data, Dumper=_BlockScalarDumper, sort_keys=False)


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
        print(f"build_generation_diff failed, skipping diff metadata: {e}")  # noqa: T201
        return None

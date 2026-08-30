"""Pure-function YAML structural assertions, safe for every test tier."""

import difflib
import re

import yaml
from name_rules import (
    MAX_EDGE_KEY_LENGTH,
    describe_rule,
    grapheme_length,
    is_control_char,
    is_valid_name,
    truncate_graphemes,
)


def path_matches(path, allowed_paths: list[str]) -> bool:
    """Match a path (list of keys) against patterns of dotted keys with `*` wildcards."""
    for allowed in allowed_paths:
        allowed_parts = allowed.split(".")
        if len(path) != len(allowed_parts):
            continue
        if all(a == "*" or a == p for p, a in zip(path, allowed_parts)):
            return True
    return False


def assert_yaml_equal_except(orig, new, allowed_paths: list[str], context: str = "") -> None:
    """Assert two YAML structures are equal except at `allowed_paths`.

    Patterns are dotted keys with `*` wildcards, e.g. `['triggers', 'jobs.*.body']`.
    """

    def compare(o, n, path):
        if path_matches(path, allowed_paths):
            return
        if type(o) is not type(n):
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
        elif o != n:
            diff = "\n".join(
                difflib.unified_diff([str(o)], [str(n)], fromfile="original", tofile="response", lineterm=""),
            )
            raise AssertionError(f"Value mismatch at {'.'.join(path)}:\n{diff}")

    try:
        compare(orig, new, [])
    except AssertionError as e:
        diff = "\n".join(
            difflib.unified_diff(
                yaml.dump(orig, sort_keys=True, allow_unicode=True).splitlines(),
                yaml.dump(new, sort_keys=True, allow_unicode=True).splitlines(),
                fromfile="original",
                tofile="response",
                lineterm="",
            ),
        )
        raise AssertionError(f"{context}\n{e}\nFull YAML diff:\n{diff}")


def _as_dict(yaml_str_or_dict):
    return yaml.safe_load(yaml_str_or_dict) if isinstance(yaml_str_or_dict, str) else yaml_str_or_dict


def assert_yaml_section_contains_all(orig, new, section: str, context: str = "") -> None:
    """Assert all items in `orig[section]` are present and unchanged in `new[section]`.

    New items in `new[section]` are allowed.
    """
    orig_section = _as_dict(orig).get(section, {})
    new_section = _as_dict(new).get(section, {})

    for key, value in orig_section.items():
        assert key in new_section, f"{context}: Key '{key}' missing in '{section}'"
        assert new_section[key] == value, (
            f"{context}: Value for '{section}.{key}' changed.\n"
            f"Original: {value}\nNew: {new_section[key]}"
        )


def assert_yaml_has_ids(yaml_str_or_dict, context: str = "") -> None:
    """Assert every job, trigger, and edge has a non-empty `id`."""
    data = _as_dict(yaml_str_or_dict)
    for kind in ("jobs", "triggers", "edges"):
        singular = kind[:-1].title()
        for item_key, item_data in data.get(kind, {}).items():
            assert "id" in item_data, f"{context}: {singular} '{item_key}' missing 'id' field."
            assert item_data["id"] not in (None, "", []), (
                f"{context}: {singular} '{item_key}' has empty 'id' field."
            )


def assert_yaml_jobs_have_body(yaml_str_or_dict, context: str = "") -> None:
    """Assert every job has a non-empty `body`."""
    for job_key, job_data in _as_dict(yaml_str_or_dict).get("jobs", {}).items():
        assert "body" in job_data, f"{context}: Job '{job_key}' missing 'body' field."
        assert job_data["body"] not in (None, "", []), f"{context}: Job '{job_key}' has empty 'body' field."


def assert_no_special_chars(yaml_str_or_dict, context: str = "") -> None:
    """Assert every name in the workflow obeys the active step-name rule.

    Covers job keys, job names, trigger keys and edge endpoint references, and
    uses `is_valid_name`, so it checks the length cap as well as the character
    set. Checking only job names with a character-set regex is how a name that
    was pushed over 100 characters by a uniquifying suffix, and a trigger key
    that was never sanitized at all, both went unnoticed.

    Also checks referential integrity: every edge endpoint must name something
    that exists. A character check alone passes a perfectly well-formed name
    that happens to point at no step, which is what a broken key mapping or a
    stray sentinel produces.

    The rule is whichever one `name_rules` has active, so this assertion tracks
    the sanitizer instead of restating it.
    """
    data = _as_dict(yaml_str_or_dict)

    def check(value, descriptor):
        assert is_valid_name(value), (
            f"{context}: {descriptor} '{value}' does not obey the step-name rule. {describe_rule()}"
        )

    # `jobs:` with nothing under it parses as None, which is valid YAML.
    jobs = data.get("jobs") or {}
    triggers = data.get("triggers") or {}
    edges = data.get("edges") or {}

    for job_key, job_data in jobs.items():
        check(str(job_key), f"Job key '{job_key}'")
        if (job_data or {}).get("name"):
            check(str(job_data["name"]), f"Job '{job_key}' name")

    for trigger_key in triggers:
        check(str(trigger_key), f"Trigger key '{trigger_key}'")

    for edge_key, raw_edge in edges.items():
        edge = raw_edge or {}
        for field, targets, what in (
            ("source_job", jobs, "job"),
            ("target_job", jobs, "job"),
            ("source_trigger", triggers, "trigger"),
            ("target_trigger", triggers, "trigger"),
        ):
            if edge.get(field):
                value = str(edge[field])
                check(value, f"Edge '{edge_key}' {field}")
                assert value in targets, (
                    f"{context}: Edge '{edge_key}' {field} '{value}' is not a {what} "
                    f"in this workflow (have: {sorted(targets)})."
                )

        _check_edge_key(edge_key, edge, context)


def _check_edge_key(edge_key: str, edge_data: dict, context: str) -> None:
    """Assert an edge's key is the label its own endpoints imply.

    Deliberately does not split the key on "->" — under the permissive rule
    "->" is a legal run of characters inside a step name, so that split is
    ambiguous. The endpoint fields carry the real identity, so the key is
    checked against them instead. This mirrors `_edge_label` in workflow_chat:
    endpoints known means the key is derived, both here and there.
    """
    edge_key = str(edge_key)

    assert grapheme_length(edge_key) <= MAX_EDGE_KEY_LENGTH, (
        f"{context}: Edge key '{edge_key}' is {grapheme_length(edge_key)} graphemes, "
        f"over the {MAX_EDGE_KEY_LENGTH} limit."
    )

    source = edge_data.get("source_job") or edge_data.get("source_trigger")
    target = edge_data.get("target_job") or edge_data.get("target_trigger")

    if not (source and target):
        # Nothing to derive the label from; just make sure it is storable.
        assert not any(is_control_char(ch) for ch in edge_key), (
            f"{context}: Edge key '{edge_key}' contains a control character."
        )
        return

    label = f"{source}->{target}"

    # A workflow may hold more than one edge between the same pair (an
    # on_success and an on_failure edge), so the sanitizer suffixes duplicates
    # — and it makes room for the suffix inside the cap rather than appending
    # past it. So the key is a grapheme prefix of the label, optionally with a
    # `-N` tail. Mirror that rule rather than restating a simpler one.
    candidates = [edge_key]
    tail = _COLLISION_SUFFIX.search(edge_key)
    if tail:
        candidates.append(edge_key[: tail.start()])

    assert any(
        candidate == truncate_graphemes(label, grapheme_length(candidate))
        for candidate in candidates
    ), (
        f"{context}: Edge key '{edge_key}' does not match its own endpoints "
        f"(expected '{truncate_graphemes(label, MAX_EDGE_KEY_LENGTH)}', "
        f"optionally trimmed for a -N suffix)."
    )


_COLLISION_SUFFIX = re.compile(r"-\d+$")

"""Pure-function YAML structural assertions, safe for every test tier."""

import difflib
import re

import yaml


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
                difflib.unified_diff([str(o)], [str(n)], fromfile="original", tofile="response", lineterm="")
            )
            raise AssertionError(f"Value mismatch at {'.'.join(path)}:\n{diff}")

    try:
        compare(orig, new, [])
    except AssertionError as e:
        diff = "\n".join(
            difflib.unified_diff(
                yaml.dump(orig, sort_keys=True).splitlines(),
                yaml.dump(new, sort_keys=True).splitlines(),
                fromfile="original",
                tofile="response",
                lineterm="",
            )
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


_SPECIAL_CHAR = re.compile(r"[^a-zA-Z0-9\s\-_]")


def assert_no_special_chars(yaml_str_or_dict, context: str = "") -> None:
    """Assert job names and edge source/target/keys use only [A-Za-z0-9 _-]."""
    data = _as_dict(yaml_str_or_dict)

    def check(value, descriptor):
        match = _SPECIAL_CHAR.search(value)
        assert not match, f"{context}: {descriptor} '{value}' contains special character '{match.group(0)}'"

    for job_key, job_data in data.get("jobs", {}).items():
        if job_data.get("name"):
            check(str(job_data["name"]), f"Job '{job_key}' name")

    for edge_key, edge_data in data.get("edges", {}).items():
        for field in ("source_job", "target_job"):
            if edge_data.get(field):
                check(str(edge_data[field]), f"Edge '{edge_key}' {field}")

        if "->" in edge_key:
            source_part, target_part = edge_key.split("->", 1)
            check(source_part, f"Edge key '{edge_key}' source part")
            check(target_part, f"Edge key '{edge_key}' target part")

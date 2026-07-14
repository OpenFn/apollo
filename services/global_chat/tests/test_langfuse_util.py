"""Unit tests for the should_track gate in services/langfuse_util.py."""
import sys
from pathlib import Path

services_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(services_dir))

from langfuse_util import should_track, build_tags, build_generation_diff, mask_secrets  # noqa: E402, I001


def test_metrics_opt_in_true_is_tracked() -> None:
    assert should_track({"metrics_opt_in": True}) is True


def test_metrics_opt_in_false_is_not_tracked() -> None:
    assert should_track({"metrics_opt_in": False}) is False


def test_missing_metrics_opt_in_is_not_tracked() -> None:
    assert should_track({}) is False


def test_persona_does_not_affect_gate() -> None:
    # Persona is for tagging only; the gate is metrics_opt_in.
    payload = {"meta": {"user": {"persona": "core-contributor"}}}
    assert should_track(payload) is False


def test_force_overrides_gate() -> None:
    assert should_track({}, force=True) is True


def test_build_tags_includes_persona() -> None:
    assert build_tags("global_chat", {"persona": "core-contributor"}) == [
        "global_chat",
        "core-contributor",
    ]
    assert build_tags("global_chat", {"persona": "user"}) == [
        "global_chat",
        "user",
    ]


def test_build_tags_without_persona() -> None:
    assert build_tags("global_chat", {}) == ["global_chat"]
    assert build_tags("global_chat", None) == ["global_chat"]


def test_diff_none_when_nothing_generated() -> None:
    assert build_generation_diff("fn(s => s);", None) is None
    assert build_generation_diff("fn(s => s);", "") is None


def test_diff_marks_only_generated_lines_as_added() -> None:
    original = "get('/patients');\n\nfn(state => {\n  console.log(state.data);\n  return state;\n});"
    generated = "get('/patients');\n\nfn(state => {\n  console.log(state.data);\n  if (!state.data) {\n    throw new Error('no data');\n  }\n  return state;\n});"
    meta = build_generation_diff(original, generated)
    diff = meta["generation_diff"]
    # Pre-existing user quirk appears as context, not as generated
    assert "   console.log(state.data);" in diff.splitlines()
    assert "+  console.log(state.data);" not in diff
    assert "+  if (!state.data) {" in diff
    assert meta["diff_stats"] == {"lines_added": 3, "lines_removed": 0}


def test_diff_from_scratch_when_no_original() -> None:
    meta = build_generation_diff(None, "fn(s => s);")
    assert meta["diff_stats"] == {"lines_added": 1, "lines_removed": 0}
    assert "+fn(s => s);" in meta["generation_diff"]


def test_yaml_mode_ignores_formatting_only_changes() -> None:
    original = 'name: "wf"\njobs:\n  a:\n    adaptor: "@openfn/language-http@6.5.1"\n'
    reserialized = "name: wf\njobs:\n  a:\n    adaptor: '@openfn/language-http@6.5.1'\n"
    meta = build_generation_diff(original, reserialized, yaml_mode=True)
    assert meta["generation_diff"] == ""
    assert meta["diff_stats"] == {"lines_added": 0, "lines_removed": 0}


def test_yaml_mode_diffs_job_bodies_line_by_line() -> None:
    original = "jobs:\n  a:\n    body: \"get(x);\\nfn(s => s);\\n\"\n"
    generated = "jobs:\n  a:\n    body: |\n      get(x);\n      fn(s => s);\n      post(y);\n"
    meta = build_generation_diff(original, generated, yaml_mode=True)
    # Both sides normalize to block scalars, so only the new line is added
    assert meta["diff_stats"] == {"lines_added": 1, "lines_removed": 0}
    assert "+      post(y);" in meta["generation_diff"]


def test_yaml_mode_falls_back_to_raw_diff_on_invalid_yaml() -> None:
    meta = build_generation_diff("{not: valid: yaml", "still generated", yaml_mode=True)
    assert meta is not None
    assert "+still generated" in meta["generation_diff"]
def test_mask_redacts_api_key_at_any_depth() -> None:
    # Shape of @observe-captured input: {"args": [...], "kwargs": {...}}
    data = {"args": ["question"], "kwargs": {"api_key": "sk-ant-abc123", "code": "fn(s => s);"}}
    masked = mask_secrets(data)
    assert masked["kwargs"]["api_key"] == "[REDACTED]"
    assert masked["kwargs"]["code"] == "fn(s => s);"
    assert masked["args"] == ["question"]


def test_mask_redacts_all_secret_key_names() -> None:
    data = {"anthropic_api_key": "abc", "Authorization": "Bearer xyz", "model": "claude"}
    masked = mask_secrets(data)
    assert masked["anthropic_api_key"] == "[REDACTED]"
    assert masked["Authorization"] == "[REDACTED]"
    assert masked["model"] == "claude"


def test_mask_redacts_key_shaped_strings_in_free_text() -> None:
    masked = mask_secrets("client = Anthropic(api_key='sk-ant-api03-xYz_9')")
    assert "sk-ant" not in masked
    assert masked == "client = Anthropic(api_key='[REDACTED]')"


def test_mask_preserves_none_and_non_string_values() -> None:
    assert mask_secrets({"api_key": None}) == {"api_key": None}
    assert mask_secrets({"usage": {"input_tokens": 5}}) == {"usage": {"input_tokens": 5}}
    number = 42
    assert mask_secrets(number) == number


def test_mask_traverses_lists() -> None:
    data = [{"api_key": "secret"}, "plain text"]
    assert mask_secrets(data) == [{"api_key": "[REDACTED]"}, "plain text"]

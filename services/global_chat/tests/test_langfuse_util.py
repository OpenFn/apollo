"""Unit tests for the should_track gate in services/langfuse_util.py."""
import sys
from pathlib import Path

services_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(services_dir))

from langfuse_util import should_track, build_tags, mask_secrets  # noqa: E402, I001


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

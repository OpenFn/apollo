"""Unit tests for the should_track gate in services/langfuse_util.py."""
import sys
from pathlib import Path

services_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(services_dir))

from langfuse_util import should_track, build_tags  # noqa: E402, I001


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

"""Unit tests for the central chat-model selection in `services/models.py`.

No real model calls, pure resolution logic. The repo-root conftest marks
everything under a `unit/` dir as `unit` and blocks real client construction.
"""

import models as m
import pytest

_WORKFLOW_ENV = m.CHAT_SERVICE_MODELS["workflow_chat"]["env"]


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Clear all per-service overrides so the real environment can't skew tests."""
    for cfg in m.CHAT_SERVICE_MODELS.values():
        monkeypatch.delenv(cfg["env"], raising=False)


def test_unlisted_service_uses_default():
    # A service with no entry (e.g. doc_agent_chat, or none at all) uses the default.
    assert m.preferred_chat_model() == m.CHAT_MODEL_DEFAULT
    assert m.preferred_chat_model("doc_agent_chat") == m.CHAT_MODEL_DEFAULT


def test_per_service_defaults():
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_SONNET
    assert m.preferred_chat_model("job_chat") == m.CLAUDE_OPUS
    assert m.preferred_chat_model("global_chat") == m.CLAUDE_OPUS


def test_env_var_overrides_its_service_default(monkeypatch):
    # Also proves the env value is alias-resolved ("claude-opus" -> full ID).
    monkeypatch.setenv(_WORKFLOW_ENV, "claude-opus")
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_OPUS


def test_env_var_is_scoped_to_one_service(monkeypatch):
    # Setting one service's var must not affect another service.
    monkeypatch.setenv(_WORKFLOW_ENV, "claude-haiku")
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_HAIKU
    assert m.preferred_chat_model("job_chat") == m.CLAUDE_OPUS  # unaffected

"""Unit tests for the central chat-model selection in `services/models.py`.

No real model calls, pure resolution logic. The repo-root conftest marks
everything under a `unit/` dir as `unit` and blocks real client construction.
"""

import models as m
import pytest

_WORKFLOW_ENV = m.CHAT_SERVICE_MODELS["workflow_chat"]["env"]


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Clear the global and all per-service overrides so the real environment
    can't skew tests."""
    monkeypatch.delenv(m.CHAT_MODEL_ENV, raising=False)
    for cfg in m.CHAT_SERVICE_MODELS.values():
        monkeypatch.delenv(cfg["env"], raising=False)


# --- defaults ---------------------------------------------------------------

def test_unlisted_service_uses_global_default():
    # A service with no entry (or none at all) falls back to CHAT_MODEL_DEFAULT.
    assert m.preferred_chat_model() == m.CHAT_MODEL_DEFAULT
    assert m.preferred_chat_model("doc_agent_chat") == m.CHAT_MODEL_DEFAULT


def test_per_service_defaults():
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_SONNET
    assert m.preferred_chat_model("job_chat") == m.CLAUDE_OPUS


# --- precedence -------------------------------------------------------------

def test_per_service_env_overrides_its_default(monkeypatch):
    # Also proves the env value is alias-resolved ("claude-opus" -> full ID).
    monkeypatch.setenv(_WORKFLOW_ENV, "claude-opus")
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_OPUS


def test_global_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv(m.CHAT_MODEL_ENV, "claude-sonnet")
    # applies to a service with no per-service env set...
    assert m.preferred_chat_model("job_chat") == m.CLAUDE_SONNET
    # ...and to an unlisted service
    assert m.preferred_chat_model("doc_agent_chat") == m.CLAUDE_SONNET


def test_per_service_env_beats_global_env(monkeypatch):
    # Global says "force everything to opus", but workflow pins itself to sonnet.
    monkeypatch.setenv(m.CHAT_MODEL_ENV, "claude-opus")
    monkeypatch.setenv(_WORKFLOW_ENV, "claude-sonnet")
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_SONNET  # per-service wins
    assert m.preferred_chat_model("job_chat") == m.CLAUDE_OPUS         # global applies here

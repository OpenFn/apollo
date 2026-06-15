"""Unit tests for the central chat-model selection in `services/models.py`.

No real model calls — pure resolution logic. The repo-root conftest marks
everything under a `unit/` dir as `unit` and blocks real client construction.
"""

import models as m
import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Ensure a stray APOLLO_CHAT_MODEL in the real environment can't skew tests."""
    monkeypatch.delenv(m.CHAT_MODEL_ENV, raising=False)


# --- preferred_chat_model: precedence ---------------------------------------

def test_preferred_defaults_to_opus_when_nothing_set():
    assert m.preferred_chat_model() == m.CLAUDE_OPUS
    assert m.preferred_chat_model(None) == m.CLAUDE_OPUS


def test_preferred_uses_config_value_when_no_env():
    assert m.preferred_chat_model("claude-sonnet") == m.CLAUDE_SONNET
    # full IDs pass through unchanged
    assert m.preferred_chat_model("claude-opus-4-7") == "claude-opus-4-7"


def test_preferred_env_overrides_config(monkeypatch):
    # Also proves the env value is alias-resolved ("claude-sonnet" -> full ID).
    monkeypatch.setenv(m.CHAT_MODEL_ENV, "claude-sonnet")
    assert m.preferred_chat_model("claude-opus") == m.CLAUDE_SONNET

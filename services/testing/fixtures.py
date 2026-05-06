"""Shared pytest fixtures and small helpers for Apollo service tests."""
from __future__ import annotations

import pytest

from testing.anthropic_mock import MockAnthropic


@pytest.fixture
def fake_api_key() -> str:
    return "sk-test"


@pytest.fixture
def mock_anthropic() -> MockAnthropic:
    return MockAnthropic()


@pytest.fixture
def test_hooks_factory():
    """Build a `test_hooks` dict in one call.

    Pass `anthropic=` a MockAnthropic to wire its httpx client; pass any
    other kwargs to override / extend the dict.
    """
    def _factory(*, anthropic: MockAnthropic | None = None, **overrides) -> dict:
        opts: dict = {"tool_calls": []}
        if anthropic is not None:
            opts["anthropic_http_client"] = anthropic.httpx_client
        opts.update(overrides)
        return opts

    return _factory


def make_global_chat_payload(content: str, **overrides) -> dict:
    """Minimal valid payload for global_chat.main()."""
    payload = {"content": content, "api_key": "sk-test"}
    payload.update(overrides)
    return payload


def make_workflow_chat_payload(content: str, **overrides) -> dict:
    """Minimal valid payload for workflow_chat.main()."""
    payload = {"content": content, "api_key": "sk-test", "history": []}
    payload.update(overrides)
    return payload


def make_job_chat_payload(content: str, **overrides) -> dict:
    """Minimal valid payload for job_chat.main()."""
    payload = {"content": content, "api_key": "sk-test"}
    payload.update(overrides)
    return payload

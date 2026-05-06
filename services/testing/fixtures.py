"""Shared pytest fixtures for Apollo service tests."""
from __future__ import annotations

import pytest

from testing.anthropic_mock import MockAnthropic


@pytest.fixture
def test_hooks_factory():
    """Build a `test_hooks` dict for `main(payload, test_hooks)`.

    Pass `anthropic=` a MockAnthropic to wire its httpx client; pass any
    other key as a kwarg (e.g. `tool_calls=[]`, `tool_stubs={...}`).
    """
    def _factory(*, anthropic: MockAnthropic | None = None, **overrides) -> dict:
        opts: dict = {}
        if anthropic is not None:
            opts["anthropic_http_client"] = anthropic.httpx_client
        opts.update(overrides)
        return opts

    return _factory

"""Repo-root pytest configuration.

- Auto-applies a tier marker (`unit` / `service` / `integration` /
  `acceptance`) based on the test's path. The directory IS the marker.
- For tests marked `unit`, blocks network, subprocess, DB, and LLM client
  construction so accidental I/O fails loud instead of timing out.
"""

from unittest.mock import patch

import pytest


_TIER_DIRS = ("unit", "service", "integration", "acceptance")

_BLOCKED_TARGETS = (
    ("socket.socket.connect", "socket.connect()"),
    ("subprocess.run", "subprocess.run()"),
    ("subprocess.Popen", "subprocess.Popen()"),
    ("psycopg2.connect", "psycopg2.connect()"),
    # Block LLM client construction, not first request — earlier failure,
    # easier to trace.
    ("anthropic.Anthropic.__init__", "anthropic.Anthropic()"),
    ("anthropic.AsyncAnthropic.__init__", "anthropic.AsyncAnthropic()"),
    ("openai.OpenAI.__init__", "openai.OpenAI()"),
    ("openai.AsyncOpenAI.__init__", "openai.AsyncOpenAI()"),
)


class UnitTestViolation(RuntimeError):
    """Raised when a unit test attempts a forbidden operation."""


def _make_blocker(operation):
    def _block(*_args, **_kwargs):
        raise UnitTestViolation(
            f"Unit tests may not perform `{operation}`. Move this test to "
            "tests/service/ or tests/integration/ if real I/O is needed. "
            "See conftest.py at the repo root for the policy."
        )

    return _block


def pytest_collection_modifyitems(items):
    for item in items:
        for tier in _TIER_DIRS:
            if tier in item.path.parts:
                item.add_marker(getattr(pytest.mark, tier))
                break


@pytest.fixture(autouse=True)
def _enforce_unit_isolation(request):
    if "unit" not in request.keywords:
        yield
        return

    patches = []
    for target, label in _BLOCKED_TARGETS:
        try:
            p = patch(target, side_effect=_make_blocker(label))
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            continue

    try:
        yield
    finally:
        for p in patches:
            p.stop()

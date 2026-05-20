"""Repo-root pytest configuration.

- Auto-applies a tier marker (`unit` / `service` / `integration` /
  `acceptance`) based on the test's path. The directory IS the marker.
- For tests marked `unit`, blocks network, subprocess, DB, and LLM client
  construction so accidental I/O fails loud instead of timing out.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from dotenv import load_dotenv


# Load services/.env into the pytest process so the judge (running in-process)
# can read ANTHROPIC_API_KEY etc. Services load this same .env themselves via
# entry.py — we point at the same file rather than maintaining a separate copy
# at the repo root. `override=False` means real env vars win.
load_dotenv(Path(__file__).parent / "services" / ".env", override=False)


# The spec collector picks up acceptance test markdown specs from
# services/<svc>/tests/acceptance/*.md and turns them into pytest items.
pytest_plugins = ["testing.spec_collector"]


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

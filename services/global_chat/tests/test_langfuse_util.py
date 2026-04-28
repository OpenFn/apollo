"""
Unit tests for the should_track gate in services/langfuse_util.py.

Pins the temporary "employees only" behavior. When the opt-in/out UX ships
and the gate swaps back to metrics_opt_in, these tests will fail and tell
the next person to update them.
"""
import sys
from pathlib import Path

services_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(services_dir))

from langfuse_util import should_track  # noqa: E402


def test_employee_is_tracked() -> None:
    assert should_track({"user": {"employee": True}}) is True


def test_non_employee_is_not_tracked() -> None:
    assert should_track({"user": {"employee": False}}) is False
    assert should_track({"user": {}}) is False
    assert should_track({}) is False


def test_metrics_opt_in_alone_does_not_track() -> None:
    # Temporary employee-only gate: metrics_opt_in is ignored until the UX ships.
    assert should_track({"metrics_opt_in": True}) is False


def test_force_overrides_gate() -> None:
    assert should_track({}, force=True) is True

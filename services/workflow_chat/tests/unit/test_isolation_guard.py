"""Smoke tests for the unit-tier isolation guard in the root conftest.py."""

import subprocess

import pytest


def test_subprocess_run_is_blocked():
    with pytest.raises(RuntimeError, match="Unit tests may not perform"):
        subprocess.run(["echo", "hello"])


def test_anthropic_construction_is_blocked():
    from anthropic import Anthropic

    with pytest.raises(RuntimeError, match="Unit tests may not perform"):
        Anthropic(api_key="fake-key")

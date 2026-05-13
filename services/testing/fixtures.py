"""Pytest fixtures shared across acceptance and integration tests.

Registered via `pytest_plugins = ["testing.fixtures"]` in the repo-root
`conftest.py` so any test can request these fixtures by name.
"""

import pytest

from testing.apollo_client import ApolloClient


@pytest.fixture(scope="session")
def apollo_client() -> ApolloClient:
    """Session-scoped client for dispatching to chat services.

    Today: subprocess-based stub. The integration tier will swap the
    underlying implementation for a real HTTP client backed by a long-lived
    bun server, without changing this fixture's interface.
    """
    return ApolloClient()

"""Keep the prompt-building tests offline.

Building a system message pulls in the adaptor list, and
`get_latest_adaptors_cached` fetches it from the GitHub API whenever the
on-disk cache is missing or more than an hour old. That made this file's tests
depend on the network and on GitHub rate limits. Stub the fetch instead — none
of these tests care what the adaptor list contains.
"""

import pytest
from workflow_chat import available_adaptors

_FAKE_ADAPTORS = {
    "common": {"version": "1.0.0", "description": "Common operations", "label": "Common"},
    "http": {"version": "1.0.0", "description": "HTTP requests", "label": "HTTP"},
}


@pytest.fixture(autouse=True)
def _offline_adaptors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        available_adaptors,
        "get_latest_adaptors_cached",
        lambda: dict(_FAKE_ADAPTORS),
    )

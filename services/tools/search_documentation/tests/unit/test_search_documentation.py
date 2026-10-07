"""Unit tests for search_documentation's delegation to the resolved backend."""

from unittest.mock import patch

import tools.search_documentation.search_documentation as m


def test_search_implementation_applies_quality_gate_to_resolved_backend(monkeypatch):
    """The 0.7 threshold is a quality gate on live traffic — it was silently
    dropped once already."""
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)

    with patch.object(m, "resolve_backend") as mock_resolve:
        backend = mock_resolve.return_value.return_value
        backend.search.return_value = []
        m._search_implementation("how do I use webhooks", 5)

    backend.search.assert_called_once_with(
        query="how do I use webhooks", top_k=5, threshold=0.7, strategy="semantic"
    )

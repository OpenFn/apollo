"""Unit tests for search_documentation's backend-flag selection.
No prior tests existed for this module."""

from unittest.mock import patch

import tools.search_documentation.search_documentation as m


def test_search_implementation_uses_legacy_pinecone_by_default(monkeypatch):
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)

    with patch.object(m, "LegacyPineconeDocsiteSearch") as mock_legacy_cls:
        mock_legacy_cls.return_value.search.return_value = []
        m._search_implementation("how do I use webhooks", 5)

    mock_legacy_cls.return_value.search.assert_called_once_with(query="how do I use webhooks", top_k=5, strategy="semantic")


def test_search_implementation_switches_to_postgres_when_flagged(monkeypatch):
    monkeypatch.setenv("DOCSITE_SEARCH_BACKEND", "postgres")

    with patch.object(m, "DocsiteSearch") as mock_pg_cls:
        mock_pg_cls.return_value.search.return_value = []
        m._search_implementation("how do I use webhooks", 5)

    mock_pg_cls.return_value.search.assert_called_once_with(query="how do I use webhooks", top_k=5, strategy="hybrid")

"""Unit tests for search_documentation's backend-flag selection.
No prior tests existed for this module."""

from unittest.mock import patch

import tools.search_documentation.search_documentation as m


def test_search_implementation_uses_legacy_pinecone_by_default(monkeypatch):
    """Characterization test: pins the exact call main made. The 0.7 threshold is
    a quality gate on live traffic — it was silently dropped once already."""
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)

    with patch.object(m, "LegacyPineconeDocsiteSearch") as mock_legacy_cls:
        mock_legacy_cls.return_value.search.return_value = []
        m._search_implementation("how do I use webhooks", 5)

    mock_legacy_cls.return_value.search.assert_called_once_with(
        query="how do I use webhooks", top_k=5, threshold=0.7, strategy="semantic"
    )


def test_search_implementation_uses_semantic_with_same_threshold_on_postgres(monkeypatch):
    """Postgres must apply the identical quality gate. Hybrid's RRF score has a
    ~0.033 ceiling — it cannot be thresholded, and renders as a constant 0.03 to
    the LLM. Semantic returns true cosine similarity, directly comparable to
    Pinecone, so the same 0.7 cutoff means the same thing on both backends."""
    monkeypatch.setenv("DOCSITE_SEARCH_BACKEND", "postgres")

    with patch.object(m, "DocsiteSearch") as mock_pg_cls:
        mock_pg_cls.return_value.search.return_value = []
        m._search_implementation("how do I use webhooks", 5)

    mock_pg_cls.return_value.search.assert_called_once_with(
        query="how do I use webhooks", top_k=5, threshold=0.7, strategy="semantic"
    )

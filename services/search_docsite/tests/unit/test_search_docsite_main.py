"""Unit tests for search_docsite.main's backend selection and resolve_backend.

The `backend` payload field lets the same query be run against either backend
on demand for manual comparison.
"""

from unittest.mock import patch

import pytest
import search_docsite.search_docsite as m
from util import ApolloError


def test_main_defaults_to_pinecone_backend(monkeypatch):
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch.object(m, "LegacyPineconeDocsiteSearch") as mock_legacy_cls:
        mock_legacy_cls.return_value.search.return_value = []
        m.main({"query": "webhooks"})

    mock_legacy_cls.assert_called_once_with()
    mock_legacy_cls.return_value.search.assert_called_once_with(query="webhooks")


def test_main_payload_backend_overrides_env(monkeypatch):
    monkeypatch.setenv("DOCSITE_SEARCH_BACKEND", "pinecone")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch.object(m, "DocsiteSearch") as mock_pg_cls:
        mock_pg_cls.return_value.search.return_value = []
        m.main({"query": "webhooks", "backend": "postgres"})

    mock_pg_cls.return_value.search.assert_called_once_with(query="webhooks")


def test_main_env_selects_postgres_when_no_payload_override(monkeypatch):
    monkeypatch.setenv("DOCSITE_SEARCH_BACKEND", "postgres")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch.object(m, "DocsiteSearch") as mock_pg_cls:
        mock_pg_cls.return_value.search.return_value = []
        m.main({"query": "webhooks"})

    mock_pg_cls.return_value.search.assert_called_once_with(query="webhooks")


def test_main_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(ApolloError) as exc:
        m.main({"query": "webhooks", "backend": "sqlite"})

    assert exc.value.code == 400


def test_main_routes_index_params_per_backend(monkeypatch):
    """The two classes take different constructor params. batch_id is meaningless
    to Pinecone; collection_name is meaningless to Postgres."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch.object(m, "DocsiteSearch") as mock_pg_cls:
        mock_pg_cls.return_value.search.return_value = []
        m.main({"query": "q", "backend": "postgres", "batch_id": 3, "collection_name": "ignored"})

    mock_pg_cls.assert_called_once_with(batch_id=3)


def test_main_routes_collection_name_to_pinecone_only(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch.object(m, "LegacyPineconeDocsiteSearch") as mock_legacy_cls:
        mock_legacy_cls.return_value.search.return_value = []
        m.main({"query": "q", "backend": "pinecone", "collection_name": "docsite-202501010000", "batch_id": 9})

    mock_legacy_cls.assert_called_once_with(collection_name="docsite-202501010000")


def test_resolve_backend_defaults_to_pinecone(monkeypatch):
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)
    assert m.resolve_backend() is m.LegacyPineconeDocsiteSearch


def test_resolve_backend_reads_env(monkeypatch):
    monkeypatch.setenv("DOCSITE_SEARCH_BACKEND", "postgres")
    assert m.resolve_backend() is m.DocsiteSearch


def test_resolve_backend_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("DOCSITE_SEARCH_BACKEND", "pinecone")
    assert m.resolve_backend("postgres") is m.DocsiteSearch


def test_resolve_backend_rejects_unknown_name(monkeypatch):
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)
    with pytest.raises(ApolloError) as exc:
        m.resolve_backend("sqlite")
    assert exc.value.code == 400

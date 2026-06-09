"""Unit tests for DocsiteSearch — the Pinecone + OpenAI seam used by job_chat.

These pin the contracts most exposed by the dependency bump (langchain-pinecone
0.2.2→0.2.13, langchain-openai →1.x, pinecone 5→7):

  - the langchain `similarity_search_with_score(query=, k=, filter=)` signature
    and its `[(Document, score), ...]` return shape, consumed by `_semantic_search`
  - the pinecone `describe_index_stats().get("namespaces")` shape, consumed by
    `_get_most_recent_namespace`
  - that the module's dependency symbols still import under the new versions

Every external boundary is mocked, so no network/credentials are touched (the
repo-root conftest also blocks real anthropic/openai client construction here).
"""

from unittest.mock import MagicMock, patch

import pytest

import search_docsite.search_docsite as m
from util import ApolloError


class FakeDoc:
    """Stand-in for a langchain Document (page_content + metadata)."""

    def __init__(self, text, metadata=None):
        self.page_content = text
        self.metadata = metadata or {}


def make_search(default_top_k=5):
    """Construct DocsiteSearch offline: collection_name given (skips the
    namespace lookup) and PineconeVectorStore patched (no real client)."""
    with patch.object(m, "PineconeVectorStore", return_value=MagicMock()):
        return m.DocsiteSearch(
            collection_name="docsite-20240101",
            default_top_k=default_top_k,
            embeddings=MagicMock(),
        )


# --- _build_filter (pure logic) ------------------------------------------------

def test_build_filter_doc_title_only():
    ds = make_search()
    assert ds._build_filter(doc_title="Adaptor X") == {"doc_title": {"$eq": "Adaptor X"}}


def test_build_filter_docs_type_only():
    ds = make_search()
    assert ds._build_filter(docs_type="general_docs") == {"docs_type": {"$eq": "general_docs"}}


def test_build_filter_both_combines_with_and():
    ds = make_search()
    assert ds._build_filter(doc_title="X", docs_type="general_docs") == {
        "$and": [{"doc_title": {"$eq": "X"}}, {"docs_type": {"$eq": "general_docs"}}]
    }


def test_build_filter_none_returns_none():
    ds = make_search()
    assert ds._build_filter() is None


# --- _semantic_search (langchain return-shape contract) ------------------------

def test_semantic_search_applies_threshold_and_passes_signature():
    ds = make_search()
    ds.vectorstore.similarity_search_with_score.return_value = [
        (FakeDoc("a"), 0.9),
        (FakeDoc("b"), 0.6),
        (FakeDoc("c"), 0.4),  # below threshold, dropped
    ]

    results = ds._semantic_search(query="q", threshold=0.5)

    assert [r.score for r in results] == [0.9, 0.6]
    assert [r.text for r in results] == ["a", "b"]
    # Pin the langchain-pinecone call signature; threshold-only => k falls back to 50.
    ds.vectorstore.similarity_search_with_score.assert_called_once_with(
        query="q", k=50, filter=None
    )


def test_semantic_search_truncates_to_top_k_when_no_threshold():
    ds = make_search()
    ds.vectorstore.similarity_search_with_score.return_value = [
        (FakeDoc(t), s) for t, s in [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6)]
    ]

    results = ds._semantic_search(query="q", top_k=2)

    assert [r.text for r in results] == ["a", "b"]
    ds.vectorstore.similarity_search_with_score.assert_called_once_with(
        query="q", k=2, filter=None
    )


def test_semantic_search_defaults_to_default_top_k():
    ds = make_search(default_top_k=5)
    ds.vectorstore.similarity_search_with_score.return_value = [
        (FakeDoc(str(i)), 0.9) for i in range(7)
    ]

    # Neither top_k nor threshold given => default_top_k (5) applies.
    results = ds._semantic_search(query="q")

    assert len(results) == 5
    ds.vectorstore.similarity_search_with_score.assert_called_once_with(
        query="q", k=5, filter=None
    )


# --- _get_most_recent_namespace (pinecone describe_index_stats shape) ----------

def _patch_pinecone(namespaces):
    index = MagicMock()
    index.describe_index_stats.return_value = {"namespaces": {ns: {} for ns in namespaces}}
    client = MagicMock()
    client.Index.return_value = index
    return patch.object(m, "Pinecone", return_value=client)


def test_get_most_recent_namespace_picks_latest_valid():
    ds = make_search()
    namespaces = ["docsite-20231231", "docsite-20240101", "other", "docsite-bad"]
    with _patch_pinecone(namespaces):
        assert ds._get_most_recent_namespace() == "docsite-20240101"


def test_get_most_recent_namespace_raises_when_none_valid():
    ds = make_search()
    with _patch_pinecone(["other", "docsite-bad", "docsite-2024"]):
        with pytest.raises(ApolloError) as exc:
            ds._get_most_recent_namespace()
    assert exc.value.code == 404


# --- dependency-symbol contract ------------------------------------------------

def test_module_exposes_expected_dependency_symbols():
    # Guards against renames/removals across the langchain/pinecone/openai bump:
    # if any import broke, the module wouldn't load and these would be missing.
    assert callable(m.Pinecone)
    assert callable(m.PineconeVectorStore)
    assert callable(m.OpenAIEmbeddings)

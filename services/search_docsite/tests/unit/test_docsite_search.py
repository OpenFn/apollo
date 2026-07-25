"""Unit tests for the Postgres-backed DocsiteSearch (semantic/keyword/hybrid).

get_db_connection and register_vector_type are mocked throughout — no real
Postgres connection is made. The OpenAI embeddings client is mocked via the
lazy `_embeddings` attribute, matching the DocsiteIndexer test pattern.
"""

from unittest.mock import MagicMock, patch

import pytest

import search_docsite.search_docsite as m
from util import ApolloError


def make_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def make_search(**kwargs):
    ds = m.DocsiteSearch(**kwargs)
    ds._embeddings = MagicMock()
    ds._embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
    return ds


def patched(conn):
    return patch.object(m, "get_db_connection", return_value=conn), patch.object(m, "register_vector_type")


# --- strategy dispatch -----------------------------------------------------

def test_search_dispatches_to_semantic_strategy():
    conn, _ = make_conn()
    ds = make_search(batch_id=1)
    with patched(conn)[0], patched(conn)[1], patch.object(ds, "_semantic_search", return_value=["r"]) as mock_sem:
        result = ds.search("query", strategy="semantic")
    assert result == ["r"]
    mock_sem.assert_called_once()


def test_search_raises_on_unknown_strategy():
    conn, _ = make_conn()
    ds = make_search(batch_id=1)
    with patched(conn)[0], patched(conn)[1]:
        with pytest.raises(ApolloError) as exc:
            ds.search("query", strategy="nonsense")
    assert exc.value.code == 400


# --- _resolve_current_batch --------------------------------------------------

def test_resolve_current_batch_returns_newest_complete_batch_id():
    conn, cur = make_conn()
    cur.fetchone.return_value = (9,)
    ds = make_search()
    assert ds._resolve_current_batch(conn) == 9


def test_resolve_current_batch_raises_when_none_complete():
    conn, cur = make_conn()
    cur.fetchone.return_value = None
    ds = make_search()
    with pytest.raises(ApolloError) as exc:
        ds._resolve_current_batch(conn)
    assert exc.value.code == 404


# --- _semantic_search: (top_k, threshold) fallback semantics, ported from Pinecone tests ---

def test_semantic_search_applies_threshold_and_falls_back_to_k_50():
    conn, cur = make_conn()
    cur.fetchall.return_value = [("a", "Doc A", "general_docs", 0.9), ("b", "Doc B", "general_docs", 0.4)]
    ds = make_search()

    results = ds._semantic_search(conn, batch_id=1, query="q", top_k=None, threshold=0.5, doc_title=None, docs_type=None)

    assert [r.text for r in results] == ["a"]
    params = cur.execute.call_args[0][1]
    assert params["max_k"] == 50


def test_semantic_search_truncates_to_top_k_when_no_threshold():
    conn, cur = make_conn()
    cur.fetchall.return_value = [("a", "A", "t", 0.9), ("b", "B", "t", 0.8), ("c", "C", "t", 0.7)]
    ds = make_search()

    results = ds._semantic_search(conn, batch_id=1, query="q", top_k=2, threshold=None, doc_title=None, docs_type=None)

    assert [r.text for r in results] == ["a", "b"]


def test_semantic_search_defaults_to_default_top_k():
    conn, cur = make_conn()
    cur.fetchall.return_value = [(str(i), str(i), "t", 0.9) for i in range(7)]
    ds = make_search(default_top_k=5)

    results = ds._semantic_search(conn, batch_id=1, query="q", top_k=None, threshold=None, doc_title=None, docs_type=None)

    assert len(results) == 5


# --- _keyword_search ---------------------------------------------------------

def test_keyword_search_uses_ts_rank_and_returns_results():
    conn, cur = make_conn()
    cur.fetchall.return_value = [("a", "Doc A", "general_docs", 0.5)]
    ds = make_search()

    results = ds._keyword_search(conn, batch_id=1, query="webhook", top_k=None, doc_title=None, docs_type="general_docs")

    assert len(results) == 1
    assert results[0].text == "a"
    sql = cur.execute.call_args[0][0]
    assert "ts_rank_cd" in sql
    assert "plainto_tsquery" in sql


# --- _hybrid_search ------------------------------------------------------------

def test_hybrid_search_runs_rrf_query_and_returns_results():
    conn, cur = make_conn()
    cur.fetchall.return_value = [("a", "Doc A", "general_docs", 0.032)]
    ds = make_search()

    results = ds._hybrid_search(conn, batch_id=1, query="webhook", top_k=5, doc_title=None, docs_type="general_docs")

    assert len(results) == 1
    sql = cur.execute.call_args[0][0]
    assert "FULL OUTER JOIN" in sql
    params = cur.execute.call_args[0][1]
    assert params["candidate_k"] == 50
    assert params["max_k"] == 5

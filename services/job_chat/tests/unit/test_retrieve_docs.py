"""Unit tests for job_chat.retrieve_docs pure-logic + LLM-call helpers.

Covers the parts that don't need live services:
  - generate_queries: JSON parsing, 4-query truncation, and the invalid-JSON guard
  - call_llm: happy path (text + usage) and the unexpected-error wrapper

The anthropic client is mocked; `call_llm` is patched where only its result
matters. Importing this module also exercises retrieve_docs' top-level
`from anthropic import APIConnectionError, BadRequestError, ...` — a dependency
contract that breaks loudly if any of those exception classes were renamed.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from embeddings.embeddings import SearchResult
from job_chat import retrieve_docs as rd
from job_chat.retrieve_docs import search_docs
from util import ApolloError


# --- generate_queries ----------------------------------------------------------

def test_generate_queries_truncates_to_four():
    payload = json.dumps({"queries": [{"query": f"q{i}"} for i in range(6)]})
    with patch.object(rd, "call_llm", return_value=(payload, {"input_tokens": 1})):
        queries, usage = rd.generate_queries("content", client=MagicMock())

    assert len(queries) == 4
    assert queries[0] == {"query": "q0"}
    assert usage == {"input_tokens": 1}


def test_generate_queries_raises_apollo_error_on_invalid_json():
    with patch.object(rd, "call_llm", return_value=("not json", {})):
        with pytest.raises(ApolloError) as exc:
            rd.generate_queries("content", client=MagicMock())

    assert exc.value.code == 500
    assert exc.value.type == "INVALID_LLM_RESPONSE"


# --- call_llm ------------------------------------------------------------------

def test_call_llm_returns_text_and_usage_on_success():
    message = MagicMock()
    message.content = [MagicMock(text="hello")]
    message.usage.model_dump.return_value = {"input_tokens": 5, "output_tokens": 2}
    client = MagicMock()
    client.messages.create.return_value = message

    text, usage = rd.call_llm(
        model="claude-haiku-4-5",
        temperature=0,
        system_prompt="sys",
        user_prompt="usr",
        client=client,
    )

    assert text == "hello"
    assert usage == {"input_tokens": 5, "output_tokens": 2}


def test_call_llm_wraps_unexpected_error_as_apollo_error():
    client = MagicMock()
    client.messages.create.side_effect = ValueError("boom")

    with pytest.raises(ApolloError) as exc:
        rd.call_llm(
            model="claude-haiku-4-5",
            temperature=0,
            system_prompt="sys",
            user_prompt="usr",
            client=client,
        )

    assert exc.value.code == 500
    assert exc.value.type == "UNKNOWN_ERROR"


# --- search_docs ----------------------------------------------------------------


def _fake_result(title):
    return SearchResult(f"text for {title}", {"doc_title": title, "docs_type": "general_docs"}, 0.9)


def test_search_docs_forwards_query_args_to_resolved_backend(monkeypatch):
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)

    with patch.object(rd, "resolve_backend") as mock_resolve:
        backend = mock_resolve.return_value.return_value
        backend.search.return_value = [_fake_result("A")]
        results = search_docs([{"query": "q"}], top_k=5)

    assert [r.metadata["doc_title"] for r in results] == ["A"]
    backend.search.assert_called_once_with(
        "q", top_k=5, threshold=None, strategy="semantic", docs_type="general_docs"
    )


def test_search_docs_passes_threshold_through(monkeypatch):
    """Threshold is a cosine-similarity cutoff that must reach the backend — this
    regressed once already when the backend flag was introduced, and rag.yaml's
    threshold silently stopped applying."""
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)

    with patch.object(rd, "resolve_backend") as mock_resolve:
        backend = mock_resolve.return_value.return_value
        backend.search.return_value = [_fake_result("A")]
        search_docs([{"query": "q"}], top_k=5, threshold=0.8)

    backend.search.assert_called_once_with(
        "q", top_k=5, threshold=0.8, strategy="semantic", docs_type="general_docs"
    )


def test_search_docs_accumulates_results_across_queries(monkeypatch):
    monkeypatch.delenv("DOCSITE_SEARCH_BACKEND", raising=False)

    with patch.object(rd, "resolve_backend") as mock_resolve:
        backend = mock_resolve.return_value.return_value
        backend.search.side_effect = [[_fake_result("A")], [_fake_result("B")]]
        results = search_docs([{"query": "q1"}, {"query": "q2"}], top_k=5)

    assert [r.metadata["doc_title"] for r in results] == ["A", "B"]
    assert backend.search.call_count == 2



"""Unit tests for job_chat.retrieve_docs pure-logic + LLM-call helpers.

Covers the parts that don't need live services:
  - format_context: context-string assembly
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

from job_chat import retrieve_docs as rd
from util import ApolloError


# --- format_context (pure logic) -----------------------------------------------

def test_format_context_includes_all_parts():
    out = rd.format_context(adaptor="http", code="get('/x')", history="prev")
    assert "http adaptor" in out
    assert "get('/x')" in out
    assert "prev" in out


def test_format_context_empty_when_no_inputs():
    assert rd.format_context(adaptor="", code="", history="") == ""


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

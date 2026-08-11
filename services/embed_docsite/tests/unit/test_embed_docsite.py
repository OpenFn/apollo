"""Unit tests for the embed_docsite entry point.

The service module must stay importable without any API key: the cache-warming
mode exists precisely so it can run with none. That is only true while the
OpenAI- and nltk-dependent imports stay inside main(), so the import at the top
of this file is itself part of the assertion.
"""

from unittest.mock import patch

import pytest

import embed_docsite.embed_docsite as m
from util import ApolloError

REFRESH_RESULT = {"markdown_files_downloaded": 3, "adaptor_functions_updated": True}
ALL_DOCS_TYPES = ["adaptor_docs", "general_docs", "adaptor_functions"]
HTTP_INTERNAL_ERROR = 500


def test_refresh_cache_only_warms_the_cache_without_indexing():
    """Warming must not need an OpenAI key or a write target — that is the whole
    point of a mode separate from a real indexing run."""
    with (
        patch.object(m, "refresh_cache", return_value=REFRESH_RESULT) as mock_refresh,
        patch.object(m, "load_dotenv") as mock_load_dotenv,
        patch.dict("os.environ", {}, clear=True),
    ):
        result = m.main({"refresh_cache_only": True})

    mock_refresh.assert_called_once_with(ALL_DOCS_TYPES)
    mock_load_dotenv.assert_not_called()
    assert result == {
        "target": "cache",
        "markdown_files_downloaded": 3,
        "adaptor_functions_updated": True,
    }


def test_refresh_cache_only_warms_just_the_requested_docs_types():
    """Warming a subset must not pull the whole corpus."""
    with (
        patch.object(m, "refresh_cache", return_value=REFRESH_RESULT) as mock_refresh,
        patch.object(m, "load_dotenv"),
        patch.dict("os.environ", {}, clear=True),
    ):
        m.main({"refresh_cache_only": True, "docs_to_upload": ["general_docs"]})

    mock_refresh.assert_called_once_with(["general_docs"])


def test_a_normal_run_still_requires_api_keys():
    """Guards the reordering: the early return must not have skipped the key
    check for ordinary runs."""
    with (
        patch.object(m, "refresh_cache") as mock_refresh,
        patch.object(m, "load_dotenv"),
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ApolloError) as exc,
    ):
        m.main({})

    mock_refresh.assert_not_called()
    assert exc.value.code == HTTP_INTERNAL_ERROR
    assert "OPENAI_API_KEY" in exc.value.message

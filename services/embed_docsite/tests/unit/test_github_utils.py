"""Unit tests for the GitHub fetch layer.

`requests` is mocked throughout — the repo-root conftest blocks real sockets in
the unit tier anyway. These cover the two things that historically went wrong:
how many API calls a full fetch costs, and what a rate-limited run reports.
"""

from unittest.mock import MagicMock, patch

import pytest

import embed_docsite.github_utils as m
from util import ApolloError


def make_response(status_code=200, json_body=None, headers=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    response.headers = headers or {}
    response.text = text
    response.raise_for_status.return_value = None
    return response


HTTP_TOO_MANY_REQUESTS = 429
HTTP_INTERNAL_ERROR = 500

# setup.md deliberately precedes jobs.md: GitHub returns tree entries in its own
# order, and listing them unsorted here is what makes the `sorted()` in
# `markdown_paths` load-bearing rather than incidental.
TREE_BODY = {
    "sha": "tree-sha-1",
    "truncated": False,
    "tree": [
        {"path": "docs", "type": "tree", "sha": "d0"},
        {"path": "docs/setup.md", "type": "blob", "sha": "blob-setup"},
        {"path": "docs/jobs.md", "type": "blob", "sha": "blob-jobs"},
        {"path": "adaptors/http.md", "type": "blob", "sha": "blob-http"},
        {"path": "docs/logo.png", "type": "blob", "sha": "blob-png"},
    ],
}

TREE_BODY_FILES = {item["path"]: item["sha"] for item in TREE_BODY["tree"] if item["type"] == "blob"}


def test_token_is_sent_when_set():
    """Authenticated requests get 5000/hr instead of 60/hr."""
    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}):
        headers = m._github_headers()
    assert headers["Authorization"] == "Bearer ghp_test"


def test_no_auth_header_when_token_absent():
    with patch.dict("os.environ", {}, clear=True):
        headers = m._github_headers()
    assert "Authorization" not in headers


def test_etag_is_sent_as_if_none_match():
    """304s do not count against the rate limit, so revalidation must be conditional."""
    headers = m._github_headers(etag='W/"abc"')
    assert headers["If-None-Match"] == 'W/"abc"'


def test_get_repo_tree_costs_one_request():
    """The whole point: the old contents-walk cost one request per directory."""
    with patch.object(m.requests, "get", return_value=make_response(json_body=TREE_BODY)) as mock_get:
        tree = m.get_repo_tree()

    assert mock_get.call_count == 1
    assert "git/trees/main?recursive=1" in mock_get.call_args[0][0]
    assert tree["tree_sha"] == "tree-sha-1"
    assert tree["files"] == {
        "docs/jobs.md": "blob-jobs",
        "docs/setup.md": "blob-setup",
        "adaptors/http.md": "blob-http",
        "docs/logo.png": "blob-png",
    }


def test_get_repo_tree_returns_none_on_304():
    with patch.object(m.requests, "get", return_value=make_response(status_code=304)):
        assert m.get_repo_tree(etag='W/"abc"') is None


def test_get_repo_tree_forwards_the_etag_into_the_outbound_headers():
    """The whole zero-cost-repeat-run claim rests on this wiring, not on
    `_github_headers` being correct in isolation."""
    with patch.object(m.requests, "get", return_value=make_response(status_code=304)) as mock_get:
        m.get_repo_tree(etag='W/"tree-etag"')

    assert mock_get.call_args.kwargs["headers"]["If-None-Match"] == 'W/"tree-etag"'


def test_get_repo_tree_captures_the_etag_for_the_next_run():
    """A tree read that does not return its ETag cannot be revalidated cheaply."""
    response = make_response(json_body=TREE_BODY, headers={"ETag": 'W/"tree-etag"'})
    with patch.object(m.requests, "get", return_value=response):
        tree = m.get_repo_tree()

    assert tree["etag"] == 'W/"tree-etag"'


def test_rate_limit_raises_a_rate_limit_error_not_an_indexerror():
    response = make_response(
        status_code=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800000000"},
    )
    with patch.object(m.requests, "get", return_value=response), pytest.raises(ApolloError) as exc:
        m.get_repo_tree()

    assert exc.value.code == HTTP_TOO_MANY_REQUESTS
    assert "GITHUB_TOKEN" in exc.value.message


def test_truncated_tree_is_rejected_loudly():
    """A truncated tree would silently index a partial corpus."""
    response = make_response(json_body=dict(TREE_BODY, truncated=True))
    with patch.object(m.requests, "get", return_value=response), pytest.raises(ApolloError) as exc:
        m.get_repo_tree()

    assert exc.value.code == HTTP_INTERNAL_ERROR


def test_raw_url_uses_the_same_ref_as_the_tree():
    """Bytes must match the blob SHA recorded against them."""
    assert m.raw_url("docs/jobs.md") == "https://raw.githubusercontent.com/OpenFn/docs/main/docs/jobs.md"


def test_markdown_paths_filters_by_prefix_and_extension():
    assert m.markdown_paths(TREE_BODY_FILES, "general_docs") == ["docs/jobs.md", "docs/setup.md"]
    assert m.markdown_paths(TREE_BODY_FILES, "adaptor_docs") == ["adaptors/http.md"]


def test_download_file_reads_raw_content_not_the_api():
    """raw.githubusercontent is not subject to the API rate limit; the API is."""
    with patch.object(m.requests, "get", return_value=make_response(text="# Jobs")) as mock_get:
        body = m.download_file("docs/jobs.md")

    assert body == "# Jobs"
    url = mock_get.call_args[0][0]
    assert url == "https://raw.githubusercontent.com/OpenFn/docs/main/docs/jobs.md"
    assert "api.github.com" not in url


def test_get_adaptor_function_docs_returns_docs_and_etag():
    response = make_response(json_body={"adaptors": []}, headers={"ETag": 'W/"fn-etag"'})
    with patch.object(m.requests, "get", return_value=response) as mock_get:
        result = m.get_adaptor_function_docs()

    assert result == {"docs": {"adaptors": []}, "etag": 'W/"fn-etag"'}
    assert mock_get.call_args[0][0] == m.ADAPTOR_FUNCTIONS_URL


def test_get_adaptor_function_docs_returns_none_on_304_and_sends_the_etag():
    with patch.object(m.requests, "get", return_value=make_response(status_code=304)) as mock_get:
        assert m.get_adaptor_function_docs(etag='W/"fn-etag"') is None

    assert mock_get.call_args.kwargs["headers"]["If-None-Match"] == 'W/"fn-etag"'

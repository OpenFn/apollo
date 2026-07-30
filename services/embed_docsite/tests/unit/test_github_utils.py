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


TREE_BODY = {
    "sha": "tree-sha-1",
    "truncated": False,
    "tree": [
        {"path": "docs", "type": "tree", "sha": "d0"},
        {"path": "docs/jobs.md", "type": "blob", "sha": "blob-jobs"},
        {"path": "docs/setup.md", "type": "blob", "sha": "blob-setup"},
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


def test_rate_limit_raises_a_rate_limit_error_not_an_indexerror():
    """The old code returned silently here and died later with
    `IndexError: list index out of range`, naming neither the cause nor the fix."""
    response = make_response(
        status_code=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800000000"},
    )
    with patch.object(m.requests, "get", return_value=response):
        with pytest.raises(ApolloError) as exc:
            m.get_repo_tree()

    assert exc.value.code == 429
    assert "GITHUB_TOKEN" in exc.value.message


def test_truncated_tree_is_rejected_loudly():
    """A truncated tree would silently index a partial corpus."""
    body = dict(TREE_BODY, truncated=True)
    with patch.object(m.requests, "get", return_value=make_response(json_body=body)):
        with pytest.raises(ApolloError) as exc:
            m.get_repo_tree()
    assert exc.value.code == 500


def test_raw_url_uses_the_same_ref_as_the_tree():
    """Bytes must match the blob SHA recorded against them."""
    assert m.raw_url("docs/jobs.md") == "https://raw.githubusercontent.com/OpenFn/docs/main/docs/jobs.md"


def test_markdown_paths_filters_by_prefix_and_extension():
    assert m.markdown_paths(TREE_BODY_FILES, "general_docs") == ["docs/jobs.md", "docs/setup.md"]
    assert m.markdown_paths(TREE_BODY_FILES, "adaptor_docs") == ["adaptors/http.md"]


def test_get_docs_keeps_its_return_contract():
    """DocsiteProcessor is the sole consumer and expects {name, docs} with a basename."""
    def fake_get(url, **_kwargs):
        if "git/trees" in url:
            return make_response(json_body=TREE_BODY)
        return make_response(text=f"body of {url.rsplit('/', 1)[-1]}")

    with patch.object(m.requests, "get", side_effect=fake_get):
        docs = m.get_docs("general_docs")

    assert docs == [
        {"name": "jobs.md", "docs": "body of jobs.md"},
        {"name": "setup.md", "docs": "body of setup.md"},
    ]


def test_get_docs_rejects_an_unknown_docs_type():
    with pytest.raises(ApolloError) as exc:
        m.get_docs("nonsense")
    assert exc.value.code == 400

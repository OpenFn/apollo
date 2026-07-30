"""Unit tests for the on-disk docs cache.

CACHE_DIR is monkeypatched to tmp_path throughout and every GitHub call is
patched out, mirroring services/latest_adaptors/tests/unit/test_cache_fallback.py.
The behaviour that matters most is the last group: a failed refresh must serve
the previous copy rather than fail the run.
"""

from unittest.mock import patch

import pytest

import embed_docsite.docsite_cache as m
from util import ApolloError

TREE = {
    "tree_sha": "tree-1",
    "etag": 'W/"etag-1"',
    "files": {"docs/jobs.md": "blob-jobs", "adaptors/http.md": "blob-http"},
}

FILES_IN_TREE = 2
HTTP_BAD_REQUEST = 400
HTTP_SERVICE_UNAVAILABLE = 503


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "CACHE_DIR", tmp_path / "docsite_cache")
    return tmp_path / "docsite_cache"


def warm(tree=TREE, body="content"):
    with (
        patch.object(m, "get_repo_tree", return_value=tree),
        patch.object(m, "download_file", return_value=body),
    ):
        return m.refresh_markdown_cache()


def test_first_refresh_downloads_every_file():
    assert warm() == FILES_IN_TREE


def test_unchanged_tree_downloads_nothing():
    """A 304 makes get_repo_tree return None — the cache is current and free."""
    warm()
    with (
        patch.object(m, "get_repo_tree", return_value=None) as mock_tree,
        patch.object(m, "download_file") as mock_download,
    ):
        downloaded = m.refresh_markdown_cache()

    assert downloaded == 0
    mock_download.assert_not_called()
    assert mock_tree.call_args.kwargs["etag"] == 'W/"etag-1"'


def test_only_the_changed_blob_is_redownloaded():
    warm()
    moved = {
        "tree_sha": "tree-2",
        "etag": 'W/"etag-2"',
        "files": {"docs/jobs.md": "blob-jobs-v2", "adaptors/http.md": "blob-http"},
    }
    with (
        patch.object(m, "get_repo_tree", return_value=moved),
        patch.object(m, "download_file", return_value="new") as mock_download,
    ):
        downloaded = m.refresh_markdown_cache()

    assert downloaded == 1
    assert mock_download.call_args[0][0] == "docs/jobs.md"


def test_files_removed_upstream_are_dropped_from_the_cache(cache_dir):
    warm()
    shrunk = {"tree_sha": "tree-3", "etag": 'W/"etag-3"', "files": {"docs/jobs.md": "blob-jobs"}}
    with (
        patch.object(m, "get_repo_tree", return_value=shrunk),
        patch.object(m, "download_file", return_value="content"),
    ):
        m.refresh_markdown_cache()

    assert not (cache_dir / "adaptors/http.md").exists()


def test_get_docs_cached_keeps_the_return_contract():
    warm(body="the text")
    with patch.object(m, "get_repo_tree", return_value=None):
        docs = m.get_docs_cached("general_docs")

    assert docs == [{"name": "jobs.md", "docs": "the text"}]


def test_a_failed_refresh_serves_the_cached_copy():
    """Being rate-limited must degrade, not fail the run."""
    warm(body="cached text")
    boom = ApolloError(429, "GitHub API rate limit exceeded", type="RATE_LIMITED")
    with patch.object(m, "get_repo_tree", side_effect=boom):
        docs = m.get_docs_cached("general_docs")

    assert docs == [{"name": "jobs.md", "docs": "cached text"}]


def test_a_failed_refresh_with_no_cache_raises_clearly():
    boom = ApolloError(429, "GitHub API rate limit exceeded", type="RATE_LIMITED")
    with patch.object(m, "get_repo_tree", side_effect=boom), pytest.raises(ApolloError) as exc:
        m.get_docs_cached("general_docs")

    assert exc.value.code == HTTP_SERVICE_UNAVAILABLE
    assert "no cached copy" in exc.value.message


def test_is_populated_reflects_the_manifest():
    assert m.is_populated() is False
    warm()
    assert m.is_populated() is True


def test_adaptor_functions_round_trip():
    payload = {"docs": {"adaptors": ["http"]}, "etag": 'W/"af-1"'}
    with patch.object(m, "get_adaptor_function_docs", return_value=payload):
        assert m.refresh_adaptor_functions_cache() is True

    with patch.object(m, "get_adaptor_function_docs", return_value=None):
        assert m.get_docs_cached("adaptor_functions") == {"adaptors": ["http"]}


def test_manifest_survives_a_corrupt_file(cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "manifest.json").write_text("{not json", encoding="utf-8")
    assert m.load_manifest() == {}


def test_unknown_docs_type_rejected():
    with pytest.raises(ApolloError) as exc:
        m.get_docs_cached("nonsense")
    assert exc.value.code == HTTP_BAD_REQUEST

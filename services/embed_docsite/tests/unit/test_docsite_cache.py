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

TWO_GENERAL_DOCS = {
    "tree_sha": "tree-2g",
    "etag": 'W/"etag-2g"',
    "files": {"docs/jobs.md": "blob-jobs", "docs/setup.md": "blob-setup"},
}

FILES_IN_TREE = 2
MARKDOWN_FILES_REFRESHED = 3
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


def test_a_file_missing_from_disk_is_redownloaded(cache_dir):
    """The manifest can claim a file the disk no longer has.

    Nothing upstream has moved, so the SHA comparison alone would skip the
    download and leave the corpus permanently short of one file.
    """
    warm()
    (cache_dir / "docs/jobs.md").unlink()
    with (
        patch.object(m, "get_repo_tree", return_value=TREE),
        patch.object(m, "download_file", return_value="content") as mock_download,
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


def test_read_docs_keeps_the_return_contract():
    warm(body="the text")
    docs = m.read_docs("general_docs")

    assert docs == [{"name": "jobs.md", "docs": "the text"}]


def test_read_docs_makes_no_network_calls():
    """The read path is disk-only; refreshing is the caller's job."""
    warm(body="the text")
    with (
        patch.object(m, "get_repo_tree") as mock_tree,
        patch.object(m, "download_file") as mock_download,
    ):
        m.read_docs("general_docs")

    mock_tree.assert_not_called()
    mock_download.assert_not_called()


def test_one_refresh_serves_every_markdown_docs_type():
    """Both markdown types come out of a single tree read."""
    with (
        patch.object(m, "get_repo_tree", return_value=TREE) as mock_tree,
        patch.object(m, "download_file", return_value="content"),
    ):
        m.refresh_cache(["general_docs", "adaptor_docs"])

    assert mock_tree.call_count == 1
    assert m.read_docs("general_docs") == [{"name": "jobs.md", "docs": "content"}]
    assert m.read_docs("adaptor_docs") == [{"name": "http.md", "docs": "content"}]


def test_refresh_skips_markdown_when_only_adaptor_functions_wanted():
    """Refreshing what was not asked for would download the whole corpus."""
    payload = {"docs": {"adaptors": ["http"]}, "etag": 'W/"af-1"'}
    with (
        patch.object(m, "get_repo_tree") as mock_tree,
        patch.object(m, "get_adaptor_function_docs", return_value=payload),
    ):
        m.refresh_cache(["adaptor_functions"])

    mock_tree.assert_not_called()


def test_refresh_skips_adaptor_functions_when_only_markdown_wanted():
    with (
        patch.object(m, "get_repo_tree", return_value=TREE),
        patch.object(m, "download_file", return_value="content"),
        patch.object(m, "get_adaptor_function_docs") as mock_functions,
    ):
        m.refresh_cache(["general_docs"])

    mock_functions.assert_not_called()


def test_a_failed_refresh_serves_the_cached_copy():
    """Being rate-limited must degrade, not fail the run."""
    warm(body="cached text")
    boom = ApolloError(429, "GitHub API rate limit exceeded", type="RATE_LIMITED")
    with patch.object(m, "get_repo_tree", side_effect=boom):
        m.refresh_cache(["general_docs"])

    assert m.read_docs("general_docs") == [{"name": "jobs.md", "docs": "cached text"}]


def test_a_failed_refresh_with_no_cache_raises_clearly():
    boom = ApolloError(429, "GitHub API rate limit exceeded", type="RATE_LIMITED")
    with patch.object(m, "get_repo_tree", side_effect=boom), pytest.raises(ApolloError) as exc:
        m.refresh_cache(["general_docs"])

    assert exc.value.code == HTTP_SERVICE_UNAVAILABLE
    assert "no cached copy" in exc.value.message


def test_reading_an_unpopulated_cache_raises_rather_than_reporting_empty_docs():
    """Reading before refreshing must not look like 'the docs are empty'."""
    with pytest.raises(ApolloError) as exc:
        m.read_docs("general_docs")

    assert exc.value.code == HTTP_SERVICE_UNAVAILABLE
    assert "refresh_cache must run first" in exc.value.message


def test_some_missing_markdown_files_are_skipped_with_a_warning(cache_dir):
    """A partially wiped cache should still serve what survives."""
    warm(tree=TWO_GENERAL_DOCS, body="the text")
    (cache_dir / "docs/setup.md").unlink()

    with patch.object(m.logger, "warning") as mock_warning:
        docs = m.read_docs("general_docs")

    assert docs == [{"name": "jobs.md", "docs": "the text"}]
    assert mock_warning.call_count == 1
    assert "1 cached general_docs file(s) missing from disk" in mock_warning.call_args[0][0]


def test_all_missing_markdown_files_raise_rather_than_serving_nothing(cache_dir):
    """An empty list would be indexed as 'the docs are empty', not as a failure."""
    warm()
    (cache_dir / "docs/jobs.md").unlink()

    with pytest.raises(ApolloError) as exc:
        m.read_docs("general_docs")

    assert exc.value.code == HTTP_SERVICE_UNAVAILABLE
    assert "no cached copy" in exc.value.message


def test_missing_adaptor_functions_file_raises_rather_than_filenotfound(cache_dir):
    """A 304 keeps the manifest etag current even when the file underneath is gone."""
    payload = {"docs": {"adaptors": ["http"]}, "etag": 'W/"af-1"'}
    with patch.object(m, "get_adaptor_function_docs", return_value=payload):
        m.refresh_adaptor_functions_cache()
    (cache_dir / m.ADAPTOR_FUNCTIONS_FILE).unlink()

    with pytest.raises(ApolloError) as exc:
        m.read_docs("adaptor_functions")

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

    assert m.read_docs("adaptor_functions") == {"adaptors": ["http"]}


def test_refresh_cache_reports_both_refreshes():
    """The entry point embed_docsite's refresh_cache_only mode returns."""
    with (
        patch.object(m, "refresh_markdown_cache", return_value=MARKDOWN_FILES_REFRESHED),
        patch.object(m, "refresh_adaptor_functions_cache", return_value=True),
    ):
        assert m.refresh_cache(["general_docs", "adaptor_docs", "adaptor_functions"]) == {
            "markdown_files_downloaded": MARKDOWN_FILES_REFRESHED,
            "adaptor_functions_updated": True,
        }


def test_manifest_survives_a_corrupt_file(cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "manifest.json").write_text("{not json", encoding="utf-8")
    assert m.load_manifest() == {}


def test_unknown_docs_type_rejected():
    warm()
    with pytest.raises(ApolloError) as exc:
        m.read_docs("nonsense")
    assert exc.value.code == HTTP_BAD_REQUEST

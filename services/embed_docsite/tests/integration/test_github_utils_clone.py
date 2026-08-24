"""Real-network tests for the git-backed docs checkout."""
import re

import embed_docsite.github_utils as m
import pytest

MIN_DOC_COUNT = 50
GIT_SHA_LENGTH = 40


@pytest.fixture(autouse=True)
def _reset_memo():
    m.sync_docs_repo.cache_clear()


@pytest.mark.parametrize("docs_type", ["general_docs", "adaptor_docs"])
def test_cold_clone_yields_a_usable_markdown_corpus(docs_type):
    m.sync_docs_repo()

    docs = m.read_markdown_docs(docs_type)

    assert len(docs) > MIN_DOC_COUNT
    assert all(doc["name"].endswith(".md") for doc in docs)
    assert all(doc["docs"].strip() for doc in docs)


def test_sparse_checkout_materializes_only_the_docs_directories():
    m.sync_docs_repo()

    checked_out = {path.name for path in m.CLONE_DIR.iterdir() if path.is_dir() and path.name != ".git"}

    assert checked_out == set(m.DOCS_TYPE_PREFIXES.values())


def test_second_sync_is_a_noop_and_corpus_is_unchanged():
    m.sync_docs_repo()
    before = m.read_markdown_docs("general_docs")

    # Bypass the per-process memo to force a real second sync, as a fresh
    # process would perform. An already-current checkout should fetch
    # nothing and leave the corpus untouched.
    m.sync_docs_repo.cache_clear()
    m.sync_docs_repo()
    after = m.read_markdown_docs("general_docs")

    assert before == after


def test_head_sha_is_a_git_sha():
    sha = m.sync_docs_repo()

    assert len(sha) == GIT_SHA_LENGTH
    assert re.fullmatch(r"[0-9a-f]+", sha)

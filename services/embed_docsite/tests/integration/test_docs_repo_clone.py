"""Real-network tests for the git-backed docs checkout."""
import re

import embed_docsite.docs_repo as m
import pytest

GENERAL_DOC_COUNT = 93
ADAPTOR_DOC_COUNT = 98
GIT_SHA_LENGTH = 40


@pytest.fixture(autouse=True)
def _reset_memo(monkeypatch):
    monkeypatch.setattr(m, "_synced_sha", None)


def test_cold_clone_yields_the_full_markdown_corpus():
    m.sync_docs_repo()

    general = m.read_markdown_docs("general_docs")
    adaptors = m.read_markdown_docs("adaptor_docs")

    assert len(general) == GENERAL_DOC_COUNT
    assert len(adaptors) == ADAPTOR_DOC_COUNT


def test_second_sync_is_a_noop_and_corpus_is_unchanged(monkeypatch):
    m.sync_docs_repo()
    before = m.read_markdown_docs("general_docs")

    # Bypass the per-process memo to force a real second sync, as a fresh
    # process would perform. An already-current checkout should fetch
    # nothing and leave the corpus untouched.
    monkeypatch.setattr(m, "_synced_sha", None)
    m.sync_docs_repo()
    after = m.read_markdown_docs("general_docs")

    assert before == after


def test_head_sha_is_a_git_sha():
    sha = m.sync_docs_repo()

    assert len(sha) == GIT_SHA_LENGTH
    assert re.fullmatch(r"[0-9a-f]+", sha)

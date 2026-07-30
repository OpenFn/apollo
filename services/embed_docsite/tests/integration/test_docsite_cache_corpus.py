"""Checks over the real cached docs corpus.

Reads the on-disk cache only — never contacts GitHub. Skips unless the cache has
been warmed, so a cold checkout reports "not run" rather than a failure.
"""

from unittest.mock import patch

import pytest

import embed_docsite.docsite_cache as cache
from embed_docsite.docsite_processor import DocsiteProcessor

WARM_HINT = (
    "docsite cache not populated — warm it by running embed_docsite with "
    '{"refresh_cache_only": true}, or see the Docs cache section of '
    "services/embed_docsite/README.md"
)

# Floors, not counts: the real corpus is ~93 general and ~98 adaptor docs, and
# these only have to be far enough above a stub to notice one.
MIN_CORPUS_DOCS = 50
MIN_GENERAL_DOC_CHUNKS = 100

pytestmark = pytest.mark.skipif(not cache.is_populated(), reason=WARM_HINT)


def offline():
    """Force the cache path by making any refresh attempt fail."""
    return patch.object(cache, "get_repo_tree", side_effect=OSError("network disabled for this test"))


def test_general_docs_are_served_from_cache_without_network():
    with offline() as no_network:
        docs = cache.get_docs_cached("general_docs")

    assert no_network.called, "offline() did not intercept — the seam moved"
    assert len(docs) > MIN_CORPUS_DOCS, "expected the real corpus, not a stub"
    assert all(doc["name"].endswith(".md") for doc in docs)
    assert all(doc["docs"].strip() for doc in docs), "a cached file is empty"


def test_adaptor_docs_are_served_from_cache_without_network():
    with offline() as no_network:
        docs = cache.get_docs_cached("adaptor_docs")

    assert no_network.called, "offline() did not intercept — the seam moved"
    assert len(docs) > MIN_CORPUS_DOCS
    assert all(doc["docs"].strip() for doc in docs)


def test_the_two_docs_types_do_not_overlap():
    """They share one repo and one tree call, so a prefix bug would silently
    duplicate the whole corpus into both. Names collide (docs/build/collections.md
    vs adaptors/collections.md); bodies do not."""
    with offline() as no_network:
        general = {doc["docs"] for doc in cache.get_docs_cached("general_docs")}
        adaptors = {doc["docs"] for doc in cache.get_docs_cached("adaptor_docs")}

    assert no_network.called, "offline() did not intercept — the seam moved"
    assert general
    assert adaptors
    assert not (general & adaptors)


def test_the_cached_corpus_chunks_cleanly(tmp_path):
    """The corpus has to survive the real chunker, not just exist on disk."""
    processor = DocsiteProcessor(docs_type="general_docs", output_dir=str(tmp_path / "split_sections"))
    with offline() as no_network:
        chunks, _metadata = processor.get_preprocessed_docs()

    assert no_network.called, "offline() did not intercept — the seam moved"
    assert len(chunks) > MIN_GENERAL_DOC_CHUNKS
    assert all(chunk["doc_chunk"].strip() for chunk in chunks)
    assert all(chunk["docs_type"] == "general_docs" for chunk in chunks)

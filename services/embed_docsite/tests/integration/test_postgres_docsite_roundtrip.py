"""End-to-end index-then-search against a real Postgres with pgvector.
"""

from unittest.mock import patch

import embed_docsite.docsite_indexer as indexer_module
import pytest
from embed_docsite.embed_docsite import _upload_to_postgres
from embed_docsite.tests.integration.helpers import StubEmbeddings, query
from search_docsite.search_docsite import DocsiteSearch
from util import ApolloError

DOCS = [
    {
        "name": "webhook-guide.md",
        "docs_type": "general_docs",
        "doc_chunk": "Configure a webhook trigger to start a workflow when data arrives.",
    },
    {
        "name": "cron-guide.md",
        "docs_type": "general_docs",
        "doc_chunk": "Use a cron trigger to run a workflow on a fixed schedule.",
    },
]


def index_docs(keep_batches=2):
    """Run the real Postgres upload path with stubbed embeddings."""
    with patch.object(indexer_module, "OpenAIEmbeddings", StubEmbeddings):
        return _upload_to_postgres(
            documents=[dict(doc) for doc in DOCS],
            metadata_dict={},
            docs_to_upload=["general_docs"],
            chunk_target_length=1000,
            chunk_min_length=700,
            keep_batches=keep_batches,
        )


def make_search(**kwargs):
    search = DocsiteSearch(**kwargs)
    search._embeddings = StubEmbeddings()
    return search


def test_fresh_database_migrates_indexes_and_promotes(clean_db):
    """The first run on an empty database used to strand in 'building',
    because copy_forward's SELECT left a transaction open."""
    result = index_docs()

    assert result["promoted"] is True
    rows = query("SELECT status FROM docsite_batches WHERE id = %s", (result["batch_id"],))
    assert rows[0][0] == "complete"


@pytest.mark.parametrize("strategy", ["semantic", "keyword", "hybrid"])
def test_search_returns_the_indexed_chunk(clean_db, strategy):
    """Semantic and hybrid used to fail with
    `operator does not exist: vector <=> numeric[]` on every query."""
    index_docs()
    target = DOCS[0]["doc_chunk"]

    results = make_search().search(target, strategy=strategy, top_k=3)

    assert any(result.text == target for result in results)


def test_reindexing_prunes_the_previous_batch(clean_db):
    """Pruning never ran, so every re-index permanently added a full
    docsite copy and another HNSW index."""
    first = index_docs(keep_batches=1)
    second = index_docs(keep_batches=1)

    assert first["batch_id"] in second["pruned_batches"]
    assert query("SELECT count(*) FROM docsite_batches WHERE id = %s", (first["batch_id"],))[0][0] == 0
    index_name = f"idx_docsite_chunks_hnsw_{first['batch_id']}"
    assert query("SELECT count(*) FROM pg_class WHERE relname = %s", (index_name,))[0][0] == 0


def test_reader_without_a_schema_gets_a_clear_503(clean_db):
    """With migrations moved to the indexer, a reader on an un-indexed
    database must explain itself rather than emit a psycopg2 traceback."""
    with pytest.raises(ApolloError) as exc:
        make_search().search("anything")

    assert exc.value.code == 503
    assert "embed_docsite" in exc.value.message

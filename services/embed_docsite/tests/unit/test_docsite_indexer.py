"""Unit tests for the Postgres batch-lifecycle write path.

Every DB call goes through an explicit `conn` parameter (never looked up
internally), so these tests drive a FakeConn that models psycopg2's transaction
state.
"""

from unittest.mock import MagicMock, patch

import embed_docsite.docsite_indexer as m
import psycopg2
import pytest
from embed_docsite.tests.unit.fake_conn import FakeConn
from pgvector import Vector


def test_register_vector_type_calls_pgvector_register():
    """Asserts a call, not transaction behaviour, so a MagicMock is right here."""
    conn = MagicMock()
    with patch.object(m, "register_vector") as mock_register:
        m.register_vector_type(conn)
    mock_register.assert_called_once_with(conn)


def make_indexer():
    indexer = m.DocsiteIndexer(chunk_target_length=1000, chunk_min_length=700, keep_batches=2)
    indexer._embeddings = MagicMock(model="fake-embedding-model")
    return indexer


def test_start_batch_inserts_row_and_returns_id():
    conn = FakeConn(results=[[(7,)]])
    indexer = make_indexer()

    batch_id = indexer.start_batch(conn, ["general_docs"])

    assert batch_id == 7
    assert conn.executed[0][1] == (["general_docs"], 1000, 700, "fake-embedding-model")
    assert conn.commits == 1


def test_insert_documents_embeds_and_bulk_inserts():
    conn = FakeConn()
    indexer = make_indexer()
    indexer._embeddings.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]
    documents = [
        {"name": "doc-a.md", "docs_type": "general_docs", "doc_chunk": "chunk one"},
        {"name": "doc-a.md", "docs_type": "general_docs", "doc_chunk": "chunk two"},
    ]

    with patch.object(m, "execute_values") as mock_execute_values:
        count = indexer.insert_documents(conn, batch_id=7, documents=documents, metadata_dict={})

    assert count == 2
    indexer._embeddings.embed_documents.assert_called_once_with(["chunk one", "chunk two"])
    rows = mock_execute_values.call_args[0][2]
    assert rows[0] == (7, "doc-a", "general_docs", 0, "chunk one", Vector([0.1, 0.2]))
    assert rows[1] == (7, "doc-a", "general_docs", 1, "chunk two", Vector([0.3, 0.4]))
    assert conn.commits == 1


def test_insert_documents_returns_zero_for_empty_input():
    conn = FakeConn()
    indexer = make_indexer()

    count = indexer.insert_documents(conn, batch_id=7, documents=[], metadata_dict={})

    assert count == 0
    assert conn.executed == []
    indexer._embeddings.embed_documents.assert_not_called()


def test_copy_forward_missing_docs_types_no_op_when_all_types_present():
    conn = FakeConn()
    indexer = make_indexer()

    copied = indexer.copy_forward_missing_docs_types(conn, batch_id=7, docs_types_present=m.ALL_DOCS_TYPES)

    assert copied == 0
    assert conn.executed == []


def test_copy_forward_missing_docs_types_copies_from_previous_batch():
    # Queue: the SELECT finds batch 3, then the INSERT ... SELECT reports 5 rows.
    conn = FakeConn(results=[[(3,)], 5])
    indexer = make_indexer()

    copied = indexer.copy_forward_missing_docs_types(conn, batch_id=7, docs_types_present=["general_docs"])

    assert copied == 5
    assert conn.executed[-1][1] == (7, 3, ["adaptor_docs", "adaptor_functions"])


def test_copy_forward_missing_docs_types_returns_zero_when_no_previous_batch():
    conn = FakeConn(results=[None])
    indexer = make_indexer()

    copied = indexer.copy_forward_missing_docs_types(conn, batch_id=7, docs_types_present=["general_docs"])

    assert copied == 0


def test_promote_batch_updates_status_and_chunk_count():
    conn = FakeConn()
    indexer = make_indexer()

    indexer.promote_batch(conn, batch_id=7, chunk_count=42)

    assert conn.executed[0][1] == (42, 7)
    assert conn.commits == 1


def test_prune_old_batches_deletes_batches_beyond_keep_count():
    conn = FakeConn(results=[[(3,), (2,)]])
    indexer = make_indexer()

    pruned = indexer.prune_old_batches(conn, keep_batches=2)

    assert pruned == [3, 2]
    assert conn.executed[0][1] == (2,)


def test_build_index_succeeds_when_a_prior_read_left_a_transaction_open():
    conn = FakeConn(results=[None])
    indexer = make_indexer()
    indexer.copy_forward_missing_docs_types(conn, batch_id=7, docs_types_present=["general_docs"])

    indexer.build_index(conn, batch_id=7)

    assert any("CREATE INDEX CONCURRENTLY" in sql for sql, _ in conn.executed)
    assert conn.autocommit is False


def test_prune_old_batches_completes_after_its_own_select():
    conn = FakeConn(results=[[(3,), (2,)]])
    indexer = make_indexer()

    pruned = indexer.prune_old_batches(conn, keep_batches=2)

    assert pruned == [3, 2]
    dropped = [sql for sql, _ in conn.executed if "DROP INDEX CONCURRENTLY" in sql]
    assert len(dropped) == 2
    assert conn.autocommit is False


def test_fail_batch_recovers_an_aborted_transaction():
    conn = FakeConn(fail_on="boom")
    indexer = make_indexer()
    with pytest.raises(psycopg2.ProgrammingError):
        with conn.cursor() as cur:
            cur.execute("boom")

    indexer.fail_batch(conn, batch_id=7)

    assert conn.rollbacks == 1
    sql, params = conn.executed[-1]
    assert "status = 'failed'" in sql
    assert params == (7,)

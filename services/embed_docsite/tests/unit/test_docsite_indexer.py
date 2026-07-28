"""Unit tests for the Postgres batch-lifecycle write path.

Every DB call goes through an explicit `conn` parameter (never looked up
internally), so these tests use a MagicMock connection/cursor throughout —
no real Postgres needed. `register_vector` (which needs a live connection to
look up pgvector's type oid) and the OpenAI embeddings client are both
patched out.
"""

from unittest.mock import MagicMock, patch

import embed_docsite.docsite_indexer as m


def make_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def test_register_vector_type_calls_pgvector_register():
    conn = MagicMock()
    with patch.object(m, "register_vector") as mock_register:
        m.register_vector_type(conn)
    mock_register.assert_called_once_with(conn)


def make_indexer():
    indexer = m.DocsiteIndexer(chunk_target_length=1000, chunk_min_length=700, keep_batches=2)
    indexer._embeddings = MagicMock(model="fake-embedding-model")
    return indexer


def test_start_batch_inserts_row_and_returns_id():
    conn, cur = make_conn()
    cur.fetchone.return_value = (7,)
    indexer = make_indexer()

    batch_id = indexer.start_batch(conn, ["general_docs"])

    assert batch_id == 7
    params = cur.execute.call_args[0][1]
    assert params == (["general_docs"], 1000, 700, "fake-embedding-model")
    conn.commit.assert_called_once()


def test_insert_documents_embeds_and_bulk_inserts():
    conn, cur = make_conn()
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
    assert rows[0] == (7, "doc-a", "general_docs", 0, "chunk one", [0.1, 0.2])
    assert rows[1] == (7, "doc-a", "general_docs", 1, "chunk two", [0.3, 0.4])
    conn.commit.assert_called_once()


def test_insert_documents_returns_zero_for_empty_input():
    conn, _ = make_conn()
    indexer = make_indexer()

    count = indexer.insert_documents(conn, batch_id=7, documents=[], metadata_dict={})

    assert count == 0
    indexer._embeddings.embed_documents.assert_not_called()


def test_copy_forward_missing_docs_types_no_op_when_all_types_present():
    conn, cur = make_conn()
    indexer = make_indexer()

    copied = indexer.copy_forward_missing_docs_types(conn, batch_id=7, docs_types_present=m.ALL_DOCS_TYPES)

    assert copied == 0
    cur.execute.assert_not_called()


def test_copy_forward_missing_docs_types_copies_from_previous_batch():
    conn, cur = make_conn()
    cur.fetchone.return_value = (3,)  # previous complete batch id
    cur.rowcount = 5
    indexer = make_indexer()

    copied = indexer.copy_forward_missing_docs_types(conn, batch_id=7, docs_types_present=["general_docs"])

    assert copied == 5
    insert_call = cur.execute.call_args_list[-1]
    assert insert_call[0][1] == (7, 3, ["adaptor_docs", "adaptor_functions"])


def test_copy_forward_missing_docs_types_returns_zero_when_no_previous_batch():
    conn, cur = make_conn()
    cur.fetchone.return_value = None
    indexer = make_indexer()

    copied = indexer.copy_forward_missing_docs_types(conn, batch_id=7, docs_types_present=["general_docs"])

    assert copied == 0


def test_promote_batch_updates_status_and_chunk_count():
    conn, cur = make_conn()
    indexer = make_indexer()

    indexer.promote_batch(conn, batch_id=7, chunk_count=42)

    params = cur.execute.call_args[0][1]
    assert params == (42, 7)
    conn.commit.assert_called_once()


def test_prune_old_batches_deletes_batches_beyond_keep_count():
    conn, cur = make_conn()
    cur.fetchall.return_value = [(3,), (2,)]  # older batches beyond keep_batches=2
    indexer = make_indexer()

    pruned = indexer.prune_old_batches(conn, keep_batches=2)

    assert pruned == [3, 2]
    select_call = cur.execute.call_args_list[0]
    assert select_call[0][1] == (2,)

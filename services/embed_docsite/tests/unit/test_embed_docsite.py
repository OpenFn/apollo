"""Unit tests for embed_docsite's orchestration. DocsiteProcessor/DocsiteIndexer
and get_db_connection are all mocked — this only tests call order and wiring."""

from unittest.mock import MagicMock, patch

import embed_docsite.embed_docsite as m


def test_main_orchestrates_full_batch_lifecycle_and_returns_summary():
    fake_conn = MagicMock()
    fake_indexer = MagicMock()
    fake_indexer.start_batch.return_value = 7
    fake_indexer.insert_documents.return_value = 10
    fake_indexer.copy_forward_missing_docs_types.return_value = 3
    fake_indexer.prune_old_batches.return_value = [4]

    fake_processor = MagicMock()
    fake_processor.get_preprocessed_docs.return_value = ([{"name": "a.md", "docs_type": "general_docs", "doc_chunk": "x"}], {"a.md": {}})

    with patch.object(m, "get_db_connection", return_value=fake_conn), \
         patch.object(m, "register_vector_type"), \
         patch.object(m, "DocsiteProcessor", return_value=fake_processor), \
         patch.object(m, "DocsiteIndexer", return_value=fake_indexer), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        result = m.main({"docs_to_upload": ["general_docs"], "target": "postgres"})

    fake_indexer.start_batch.assert_called_once_with(fake_conn, ["general_docs"])
    fake_indexer.insert_documents.assert_called_once()
    fake_indexer.copy_forward_missing_docs_types.assert_called_once_with(fake_conn, 7, ["general_docs"])
    fake_indexer.build_index.assert_called_once_with(fake_conn, 7)
    fake_indexer.promote_batch.assert_called_once_with(fake_conn, 7, 13)  # 10 inserted + 3 copied forward
    fake_indexer.prune_old_batches.assert_called_once_with(fake_conn)
    fake_conn.close.assert_called_once()

    assert result == {
        "target": "postgres",
        "batch_id": 7,
        "docs_types": ["general_docs"],
        "chunk_count": 10,
        "copied_forward": 3,
        "pruned_batches": [4],
        "promoted": True,
    }


def test_main_raises_when_openai_key_missing():
    from util import ApolloError
    import pytest

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ApolloError) as exc:
            m.main({})

    assert exc.value.code == 500
    assert "OPENAI_API_KEY" in exc.value.message


def test_main_defaults_docs_to_upload_to_all_types():
    fake_conn = MagicMock()
    fake_indexer = MagicMock()
    fake_indexer.start_batch.return_value = 1
    fake_indexer.insert_documents.return_value = 0
    fake_indexer.copy_forward_missing_docs_types.return_value = 0
    fake_indexer.prune_old_batches.return_value = []
    fake_processor = MagicMock()
    fake_processor.get_preprocessed_docs.return_value = ([], {})

    with patch.object(m, "get_db_connection", return_value=fake_conn), \
         patch.object(m, "register_vector_type"), \
         patch.object(m, "DocsiteProcessor", return_value=fake_processor) as mock_processor_cls, \
         patch.object(m, "DocsiteIndexer", return_value=fake_indexer), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        m.main({"target": "postgres"})

    called_docs_types = [call.kwargs["docs_type"] for call in mock_processor_cls.call_args_list]
    assert called_docs_types == m.ALL_DOCS_TYPES


def test_main_defaults_to_pinecone_target():
    """Default must match main's behavior: write to Pinecone, never open Postgres."""
    fake_indexer = MagicMock()
    fake_processor = MagicMock()
    fake_processor.get_preprocessed_docs.return_value = ([], {})

    with patch.object(m, "get_db_connection") as mock_get_conn, \
         patch.object(m, "DocsiteProcessor", return_value=fake_processor), \
         patch.object(m, "LegacyPineconeDocsiteIndexer", return_value=fake_indexer) as mock_legacy_cls, \
         patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test", "PINECONE_API_KEY": "pc-test"}):
        m.main({"docs_to_upload": ["general_docs"]})

    mock_legacy_cls.assert_called_once()
    mock_get_conn.assert_not_called()


def test_main_pinecone_target_does_not_require_postgres_url():
    """With target=pinecone the service must not touch Postgres at all, so
    POSTGRES_URL need not be set — matching main's dependency surface."""
    fake_processor = MagicMock()
    fake_processor.get_preprocessed_docs.return_value = ([], {})

    with patch.object(m, "get_db_connection") as mock_get_conn, \
         patch.object(m, "DocsiteProcessor", return_value=fake_processor), \
         patch.object(m, "LegacyPineconeDocsiteIndexer"), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test", "PINECONE_API_KEY": "pc-test"}, clear=True):
        m.main({})

    mock_get_conn.assert_not_called()


def test_main_rejects_unknown_target():
    from util import ApolloError
    import pytest

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        with pytest.raises(ApolloError) as exc:
            m.main({"target": "elasticsearch"})

    assert exc.value.code == 400


def test_postgres_upload_runs_migrations_before_registering_vector_type():
    """Order is load-bearing, not incidental: register_vector runs
    to_regtype('vector') and raises unless CREATE EXTENSION has already run."""
    calls = []
    fake_conn = MagicMock()
    fake_indexer = MagicMock()
    fake_indexer.start_batch.return_value = 7
    fake_indexer.insert_documents.return_value = 1
    fake_indexer.copy_forward_missing_docs_types.return_value = 0
    fake_indexer.prune_old_batches.return_value = []
    fake_processor = MagicMock()
    fake_processor.get_preprocessed_docs.return_value = ([], {})

    with patch.object(m, "get_db_connection", return_value=fake_conn), \
         patch.object(m, "run_migrations", side_effect=lambda _conn: calls.append("migrate")), \
         patch.object(m, "register_vector_type", side_effect=lambda _conn: calls.append("register")), \
         patch.object(m, "DocsiteProcessor", return_value=fake_processor), \
         patch.object(m, "DocsiteIndexer", return_value=fake_indexer), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        m.main({"docs_to_upload": ["general_docs"], "target": "postgres"})

    assert calls == ["migrate", "register"]

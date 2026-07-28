import os

from dotenv import load_dotenv
from embed_docsite.docsite_indexer import (
    ALL_DOCS_TYPES,
    DocsiteIndexer,
    register_vector_type,
)
from embed_docsite.docsite_processor import DocsiteProcessor
from embed_docsite.pinecone_legacy_indexer import LegacyPineconeDocsiteIndexer
from util import ApolloError, create_logger, get_db_connection

logger = create_logger("embed_docsite")

VALID_TARGETS = ("pinecone", "postgres")


def _collect_documents(docs_to_upload, docs_to_ignore, chunk_target_length, chunk_min_length):
    """Download and chunk every requested docs_type. Shared by both targets."""
    documents = []
    metadata_dict = {}
    for docs_type in docs_to_upload:
        processor = DocsiteProcessor(
            docs_type=docs_type,
            docs_to_ignore=docs_to_ignore,
            target_length=chunk_target_length,
            min_length=chunk_min_length,
        )
        type_documents, type_metadata = processor.get_preprocessed_docs()
        documents.extend(type_documents)
        metadata_dict.update(type_metadata)
    return documents, metadata_dict


def main(data: dict) -> dict:
    logger.info("Starting...")

    target = data.get("target", "pinecone")
    docs_to_upload = data.get("docs_to_upload", ALL_DOCS_TYPES)
    docs_to_ignore = data.get("docs_to_ignore", ["job-examples.md", "release-notes.md"])
    chunk_target_length = data.get("chunk_target_length", 1000)
    chunk_min_length = data.get("chunk_min_length", 700)
    keep_batches = data.get("keep_batches", 2)

    if target not in VALID_TARGETS:
        raise ApolloError(
            400,
            f"Unknown target '{target}'. Expected 'pinecone' or 'postgres'",
            type="BAD_REQUEST",
        )

    load_dotenv(override=True)

    openai_api_key = data.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        msg = "Missing API key: OPENAI_API_KEY"
        logger.error(msg)
        raise ApolloError(500, f"{msg}. Add to payload or environment", type="BAD_REQUEST")

    documents, metadata_dict = _collect_documents(
        docs_to_upload, docs_to_ignore, chunk_target_length, chunk_min_length,
    )

    if target == "pinecone":
        return _upload_to_pinecone(data, documents, metadata_dict, docs_to_upload)

    return _upload_to_postgres(
        documents, metadata_dict, docs_to_upload, chunk_target_length, chunk_min_length, keep_batches,
    )


def _upload_to_pinecone(data, documents, metadata_dict, docs_to_upload):
    """Legacy write path. Deliberately opens no Postgres connection."""
    pinecone_api_key = data.get("PINECONE_API_KEY") or os.environ.get("PINECONE_API_KEY")
    if not pinecone_api_key:
        msg = "Missing API key: PINECONE_API_KEY"
        logger.error(msg)
        raise ApolloError(500, f"{msg}. Add to payload or environment", type="BAD_REQUEST")

    index_params = {
        key: data[key]
        for key in ("collection_name", "index_name", "max_total_collections")
        if key in data
    }
    indexer = LegacyPineconeDocsiteIndexer(**index_params)
    indexer.insert_documents(documents, metadata_dict)

    return {
        "target": "pinecone",
        "collection_name": indexer.collection_name,
        "docs_types": docs_to_upload,
        "chunk_count": len(documents),
    }


def _upload_to_postgres(documents, metadata_dict, docs_to_upload, chunk_target_length, chunk_min_length, keep_batches):
    indexer = DocsiteIndexer(
        chunk_target_length=chunk_target_length,
        chunk_min_length=chunk_min_length,
        keep_batches=keep_batches,
    )

    conn = get_db_connection()
    register_vector_type(conn)

    try:
        batch_id = indexer.start_batch(conn, docs_to_upload)
        chunk_count = indexer.insert_documents(conn, batch_id, documents, metadata_dict)
        copied = indexer.copy_forward_missing_docs_types(conn, batch_id, docs_to_upload)
        indexer.build_index(conn, batch_id)
        indexer.promote_batch(conn, batch_id, chunk_count + copied)
        pruned = indexer.prune_old_batches(conn)

        return {
            "target": "postgres",
            "batch_id": batch_id,
            "docs_types": docs_to_upload,
            "chunk_count": chunk_count,
            "copied_forward": copied,
            "pruned_batches": pruned,
            "promoted": True,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    main({})

import os

from dotenv import load_dotenv
from embed_docsite.docsite_indexer import (
    ALL_DOCS_TYPES,
    DocsiteIndexer,
    create_table_if_not_exists,
    register_vector_type,
)
from embed_docsite.docsite_processor import DocsiteProcessor
from util import ApolloError, create_logger, get_db_connection

logger = create_logger("embed_docsite")


def main(data: dict) -> dict:
    logger.info("Starting...")

    docs_to_upload = data.get("docs_to_upload", ALL_DOCS_TYPES)
    docs_to_ignore = data.get("docs_to_ignore", ["job-examples.md", "release-notes.md"])
    chunk_target_length = data.get("chunk_target_length", 1000)
    chunk_min_length = data.get("chunk_min_length", 700)
    keep_batches = data.get("keep_batches", 2)

    load_dotenv(override=True)

    openai_api_key = data.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        msg = "Missing API key: OPENAI_API_KEY"
        logger.error(msg)
        raise ApolloError(500, f"{msg}. Add to payload or environment", type="BAD_REQUEST")

    indexer = DocsiteIndexer(
        chunk_target_length=chunk_target_length,
        chunk_min_length=chunk_min_length,
        keep_batches=keep_batches,
    )

    conn = get_db_connection()
    register_vector_type(conn)

    try:
        create_table_if_not_exists(conn)

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

        batch_id = indexer.start_batch(conn, docs_to_upload)
        chunk_count = indexer.insert_documents(conn, batch_id, documents, metadata_dict)
        copied = indexer.copy_forward_missing_docs_types(conn, batch_id, docs_to_upload)
        indexer.build_index(conn, batch_id)
        indexer.promote_batch(conn, batch_id, chunk_count + copied)
        pruned = indexer.prune_old_batches(conn)

        return {
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

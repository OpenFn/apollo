from contextlib import contextmanager

from langchain_openai import OpenAIEmbeddings
from pgvector import Vector
from pgvector.psycopg2 import register_vector
from psycopg2.extras import execute_values
from util import create_logger

logger = create_logger("DocsiteIndexer")

ALL_DOCS_TYPES = ["adaptor_docs", "general_docs", "adaptor_functions"]


@contextmanager
def autocommit(conn):
    """Run DDL that cannot execute inside a transaction (CREATE/DROP INDEX
    CONCURRENTLY).

    Commits first: psycopg2 refuses to change autocommit while a transaction is
    open, and a preceding SELECT is enough to open one.
    """
    previous = conn.autocommit
    conn.commit()
    conn.autocommit = True
    try:
        yield
    finally:
        conn.autocommit = previous


def register_vector_type(conn):
    """Register pgvector's psycopg2 adapters on this connection."""
    register_vector(conn)


class DocsiteIndexer:
    """
    Builds versioned "batches" of embedded docsite chunks in Postgres.

    A batch is a full, self-consistent snapshot across all docs_types. Batches
    are built invisibly (status='building'), then promoted to 'complete'
    atomically, so readers only ever see a finished batch.

    :param chunk_target_length: Target chunk size in characters (default: 1000)
    :param chunk_min_length: Minimum chunk size before merging with the next split (default: 700)
    :param keep_batches: Number of most-recent complete batches to retain when pruning (default: 2)
    """

    def __init__(self, chunk_target_length=1000, chunk_min_length=700, keep_batches=2):
        self.chunk_target_length = chunk_target_length
        self.chunk_min_length = chunk_min_length
        self.keep_batches = keep_batches
        self._embeddings = None

    @property
    def embeddings(self):
        """Lazily construct the OpenAI embeddings client."""
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings()
        return self._embeddings

    def start_batch(self, conn, docs_types):
        """Insert a new 'building' batch row and return its id."""
        sql = """
        INSERT INTO docsite_batches (status, docs_types, chunk_target_length, chunk_min_length, embedding_model)
        VALUES ('building', %s, %s, %s, %s)
        RETURNING id
        """
        with conn.cursor() as cur:
            cur.execute(sql, (docs_types, self.chunk_target_length, self.chunk_min_length, self.embeddings.model))
            batch_id = cur.fetchone()[0]
            conn.commit()
        logger.info(f"Started batch {batch_id} for docs_types={docs_types}")
        return batch_id

    def insert_documents(self, conn, batch_id, documents, metadata_dict):
        """Embed and bulk-insert chunks for this batch. Returns the number of chunks inserted."""
        if not documents:
            return 0

        texts = [doc["doc_chunk"] for doc in documents]
        embeddings = self._embed_in_batches(texts)

        doc_title_indices = {}
        rows = []
        for doc, embedding in zip(documents, embeddings):
            doc_title = doc["name"].removesuffix(".md")
            chunk_index = doc_title_indices.get(doc_title, 0)
            doc_title_indices[doc_title] = chunk_index + 1
            rows.append((batch_id, doc_title, doc["docs_type"], chunk_index, doc["doc_chunk"], Vector(embedding)))

        insert_sql = """
        INSERT INTO docsite_chunks (batch_id, doc_title, docs_type, chunk_index, text, embedding)
        VALUES %s
        """
        with conn.cursor() as cur:
            execute_values(cur, insert_sql, rows)
            conn.commit()

        logger.info(f"Inserted {len(rows)} chunks into batch {batch_id}")
        return len(rows)

    def _embed_in_batches(self, texts, batch_size=100):
        """Call the OpenAI embeddings API in batches of batch_size texts."""
        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings.extend(self.embeddings.embed_documents(batch))
        return embeddings

    def copy_forward_missing_docs_types(self, conn, batch_id, docs_types_present):
        """Copy chunks for docs_types not in this run from the previous complete batch,
        so every complete batch is a full snapshot across all docs_types. Returns rows copied."""
        missing_types = [t for t in ALL_DOCS_TYPES if t not in docs_types_present]
        if not missing_types:
            return 0

        with conn.cursor() as cur:
            cur.execute("SELECT id FROM docsite_batches WHERE status = 'complete' ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row is None:
                logger.info("No previous complete batch to copy forward from")
                return 0
            previous_batch_id = row[0]

            cur.execute(
                """
                INSERT INTO docsite_chunks (batch_id, doc_title, docs_type, chunk_index, text, embedding)
                SELECT %s, doc_title, docs_type, chunk_index, text, embedding
                FROM docsite_chunks
                WHERE batch_id = %s AND docs_type = ANY(%s)
                """,
                (batch_id, previous_batch_id, missing_types),
            )
            copied = cur.rowcount
            conn.commit()

        logger.info(f"Copied {copied} chunks forward for docs_types={missing_types} from batch {previous_batch_id}")
        return copied

    def build_index(self, conn, batch_id):
        """Build a per-batch partial HNSW index."""
        with autocommit(conn):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_docsite_chunks_hnsw_{batch_id}
                    ON docsite_chunks USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                    WHERE batch_id = {batch_id}
                    """
                )
        logger.info(f"Built HNSW index for batch {batch_id}")

    def promote_batch(self, conn, batch_id, chunk_count):
        """Flip a batch to 'complete' the moment it becomes visible to readers."""
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE docsite_batches SET status = 'complete', completed_at = now(), chunk_count = %s WHERE id = %s",
                (chunk_count, batch_id),
            )
            conn.commit()
        logger.info(f"Promoted batch {batch_id} ({chunk_count} chunks)")

    def fail_batch(self, conn, batch_id):
        """Mark a batch 'failed' after an aborted build.

        Rolls back first: the connection is in an aborted transaction from
        whatever error got us here, so any statement would raise
        InFailedSqlTransaction.
        """
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE docsite_batches SET status = 'failed' WHERE id = %s", (batch_id,))
            conn.commit()
        logger.info(f"Marked batch {batch_id} failed")

    def prune_old_batches(self, conn, keep_batches=None):
        """Delete complete batches older than the newest `keep_batches`, dropping their
        partial indexes first. Returns the list of pruned batch ids."""
        keep = keep_batches if keep_batches is not None else self.keep_batches

        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM docsite_batches WHERE status = 'complete' ORDER BY id DESC OFFSET %s",
                (keep,),
            )
            old_batch_ids = [row[0] for row in cur.fetchall()]

        for batch_id in old_batch_ids:
            with autocommit(conn):
                with conn.cursor() as cur:
                    cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS idx_docsite_chunks_hnsw_{batch_id}")
            with conn.cursor() as cur:
                cur.execute("DELETE FROM docsite_batches WHERE id = %s", (batch_id,))
                conn.commit()
            logger.info(f"Pruned batch {batch_id}")

        return old_batch_ids

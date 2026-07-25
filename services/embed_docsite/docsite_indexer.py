from typing import Optional
from psycopg2.extras import execute_values
from langchain_openai import OpenAIEmbeddings
from pgvector.psycopg2 import register_vector
from util import create_logger

logger = create_logger("DocsiteIndexer")

ALL_DOCS_TYPES = ["adaptor_docs", "general_docs", "adaptor_functions"]

CREATE_TABLES_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS docsite_batches (
    id                  BIGSERIAL PRIMARY KEY,
    status              VARCHAR(20) NOT NULL DEFAULT 'building'
                          CHECK (status IN ('building', 'complete', 'failed')),
    docs_types          TEXT[] NOT NULL,
    chunk_target_length INT NOT NULL,
    chunk_min_length    INT NOT NULL,
    embedding_model     VARCHAR(100) NOT NULL,
    chunk_count         INT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS docsite_chunks (
    id           BIGSERIAL PRIMARY KEY,
    batch_id     BIGINT NOT NULL REFERENCES docsite_batches(id) ON DELETE CASCADE,
    doc_title    VARCHAR(500) NOT NULL,
    docs_type    VARCHAR(50) NOT NULL,
    chunk_index  INT NOT NULL,
    text         TEXT NOT NULL,
    embedding    vector(1536) NOT NULL,
    text_search  tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_docsite_chunks_batch     ON docsite_chunks(batch_id);
CREATE INDEX IF NOT EXISTS idx_docsite_chunks_doc_title ON docsite_chunks(batch_id, doc_title);
CREATE INDEX IF NOT EXISTS idx_docsite_chunks_docs_type ON docsite_chunks(batch_id, docs_type);
CREATE INDEX IF NOT EXISTS idx_docsite_chunks_fts       ON docsite_chunks USING gin(text_search);
"""


def create_table_if_not_exists(conn):
    """Create the docsite_batches/docsite_chunks tables and pgvector extension if missing."""
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLES_SQL)
        conn.commit()


def register_vector_type(conn):
    """Register the pgvector adapter on this connection so Python lists convert to the `vector` type."""
    register_vector(conn)


class DocsiteIndexer:
    """
    Builds versioned "batches" of embedded docsite chunks in Postgres.

    A batch is a full, self-consistent snapshot across all docs_types. Batches
    are built invisibly (status='building'), then promoted to 'complete'
    atomically — replacing Pinecone's timestamped-namespace-per-run pattern.

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
        """Lazily construct the OpenAI embeddings client (avoids eager credential
        validation at import/instantiation time)."""
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings()
        return self._embeddings

    def start_batch(self, conn, docs_types: list) -> int:
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

    def insert_documents(self, conn, batch_id: int, documents: list, metadata_dict: dict) -> int:
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
            rows.append((batch_id, doc_title, doc["docs_type"], chunk_index, doc["doc_chunk"], embedding))

        insert_sql = """
        INSERT INTO docsite_chunks (batch_id, doc_title, docs_type, chunk_index, text, embedding)
        VALUES %s
        """
        with conn.cursor() as cur:
            execute_values(cur, insert_sql, rows)
            conn.commit()

        logger.info(f"Inserted {len(rows)} chunks into batch {batch_id}")
        return len(rows)

    def _embed_in_batches(self, texts: list, batch_size: int = 100) -> list:
        """Call the OpenAI embeddings API in batches of batch_size texts."""
        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings.extend(self.embeddings.embed_documents(batch))
        return embeddings

    def copy_forward_missing_docs_types(self, conn, batch_id: int, docs_types_present: list) -> int:
        """Copy chunks for docs_types NOT in this run from the previous complete batch,
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

    def build_index(self, conn, batch_id: int) -> None:
        """Build a per-batch partial HNSW index. Runs outside a transaction (autocommit)."""
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_docsite_chunks_hnsw_{batch_id}
                    ON docsite_chunks USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                    WHERE batch_id = {batch_id}
                    """
                )
        finally:
            conn.autocommit = False
        logger.info(f"Built HNSW index for batch {batch_id}")

    def promote_batch(self, conn, batch_id: int, chunk_count: int) -> None:
        """Flip a batch to 'complete' — the moment it becomes visible to readers."""
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE docsite_batches SET status = 'complete', completed_at = now(), chunk_count = %s WHERE id = %s",
                (chunk_count, batch_id),
            )
            conn.commit()
        logger.info(f"Promoted batch {batch_id} ({chunk_count} chunks)")

    def prune_old_batches(self, conn, keep_batches: Optional[int] = None) -> list:
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
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS idx_docsite_chunks_hnsw_{batch_id}")
            finally:
                conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute("DELETE FROM docsite_batches WHERE id = %s", (batch_id,))
                conn.commit()
            logger.info(f"Pruned batch {batch_id}")

        return old_batch_ids

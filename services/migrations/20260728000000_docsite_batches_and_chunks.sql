-- Docsite chunk storage (Postgres + pgvector).
-- Applied by services/db_migrations.py; recorded in _migrations_docs.

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

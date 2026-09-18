"""Shared helpers for the Postgres docsite integration suite."""

import hashlib
import os
import random

import psycopg2

# Importing embed_docsite pulls in LegacyPineconeDocsiteIndexer, whose
# OpenAIEmbeddings() default arg validates credentials at construction. Dummy
# placeholders only — this suite makes no OpenAI call.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("PINECONE_API_KEY", "pc-test-dummy")

TEST_URL = os.environ.get("POSTGRES_TEST_URL")

EMBEDDING_DIMENSIONS = 1536


class StubEmbeddings:
    """Deterministic stand-in for OpenAIEmbeddings.

    Identical text yields an identical vector, so querying a chunk's exact text
    puts that chunk at cosine distance 0 and therefore rank 1.
    """

    model = "stub-embedding-model"

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)

    @staticmethod
    def _vector(text):
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIMENSIONS)]


def query(sql, params=None):
    """Run a read against the test database on its own connection."""
    conn = psycopg2.connect(TEST_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()

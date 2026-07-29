"""Fixtures for the Postgres docsite integration suite.

Requires POSTGRES_TEST_URL (not POSTGRES_URL) pointing at a database with the pgvector extension
available and a role permitted to CREATE EXTENSION:

    docker run -d --name apollo-pgvector-test -e POSTGRES_PASSWORD=postgres \
        -p 5433:5432 pgvector/pgvector:pg16
    export POSTGRES_TEST_URL=postgresql://postgres:postgres@127.0.0.1:5433/postgres

The repo-root conftest blocks psycopg2.connect for `unit` tests only, so this
tier connects normally.
"""

import psycopg2
import pytest

from embed_docsite.tests.integration.helpers import TEST_URL


@pytest.fixture
def clean_db(monkeypatch):
    """An empty database: no docsite tables, no pgvector extension.

    Dropping the extension too means the reader's 'no extension' path is
    reachable, and migrations have to prove they can recreate it.
    """
    if not TEST_URL:
        pytest.skip("POSTGRES_TEST_URL not set")

    conn = psycopg2.connect(TEST_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS docsite_chunks, docsite_batches, _migrations_docs CASCADE")
        cur.execute("DROP EXTENSION IF EXISTS vector CASCADE")
    conn.close()

    monkeypatch.setenv("POSTGRES_URL", TEST_URL)
    return TEST_URL

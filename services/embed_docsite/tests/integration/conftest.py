"""Fixtures for the Postgres docsite integration suite.

Requires POSTGRES_TEST_URL (not POSTGRES_URL) pointing at a database with the pgvector extension
available and a role permitted to CREATE EXTENSION, and `bun` on the PATH (migrations are
owned by the platform runner, platform/src/db/migrate.ts):

    docker run -d --name apollo-pgvector-test -e POSTGRES_PASSWORD=postgres \
        -p 5433:5432 pgvector/pgvector:pg16
    export POSTGRES_TEST_URL=postgresql://postgres:postgres@127.0.0.1:5433/postgres

The repo-root conftest blocks psycopg2.connect for `unit` tests only, so this
tier connects normally.
"""

import os
import subprocess
from pathlib import Path

import psycopg2
import pytest
from embed_docsite.tests.integration.helpers import TEST_URL

REPO_ROOT = Path(__file__).parents[4]


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
        cur.execute("DROP TABLE IF EXISTS docsite_chunks, docsite_batches, lightning_clients, _migrations CASCADE")
        cur.execute("DROP EXTENSION IF EXISTS vector CASCADE")
    conn.close()

    monkeypatch.setenv("POSTGRES_URL", TEST_URL)
    return TEST_URL


@pytest.fixture
def migrated_db(clean_db):
    """clean_db, with every migration applied by the real `bun run migrate`."""
    # Point both targets at the test database and nothing else
    env = {**os.environ, "POSTGRES_URL": clean_db}
    env.pop("APOLLO_CLIENTS_DB_URL", None)
    subprocess.run(
        ["bun", "platform/src/db/migrate.ts"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return clean_db

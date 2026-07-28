"""Versioned schema migrations for the Python-owned docs database (POSTGRES_URL).

Applies .sql files in lexical order, records applied filenames so re-runs are a
no-op, and takes an advisory lock so concurrent starters queue.

The tracking table (_migrations_docs) and lock key are distinct from the
TypeScript runner's in platform/src/db/migrate.ts, because APOLLO_CLIENTS_DB_URL
falls back to POSTGRES_URL locally and both runners can target one database.
"""

from pathlib import Path

from util import create_logger

logger = create_logger("db_migrations")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Distinct from the TypeScript runner's 8314_2025 so the two never block each other.
MIGRATION_LOCK_KEY = 8314_2026

CREATE_TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS _migrations_docs (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _migration_files():
    """Every .sql file in the migrations directory, in lexical order."""
    if not MIGRATIONS_DIR.is_dir():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def run_migrations(conn):
    """Apply any migrations not yet recorded. Returns the count applied this run.

    Everything happens in one transaction: the advisory lock is held for its
    duration, so a racing process waits and then sees the migrations already
    recorded rather than colliding on CREATE TABLE.
    """
    files = _migration_files()

    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_KEY,))
        cur.execute(CREATE_TRACKING_TABLE_SQL)

        cur.execute("SELECT filename FROM _migrations_docs")
        already_applied = {row[0] for row in cur.fetchall()}

        pending = [f for f in files if f.name not in already_applied]
        for path in pending:
            logger.info(f"Applying migration {path.name}")
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO _migrations_docs (filename) VALUES (%s)", (path.name,))

    conn.commit()

    if pending:
        logger.info(f"Applied {len(pending)} migration(s)")

    return len(pending)

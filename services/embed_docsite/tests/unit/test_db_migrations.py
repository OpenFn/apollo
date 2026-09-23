"""Unit tests for the Python migration runner.

Mirrors the TypeScript runner in platform/src/db/migrate.ts using lexical ordering,
already-applied files skipped and an advisory lock taken. The connection and cursor
are MagicMocks.
"""

from unittest.mock import MagicMock, patch

import db_migrations as m


def make_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def test_run_migrations_takes_advisory_lock_before_applying():
    conn, cur = make_conn()
    cur.fetchall.return_value = []

    with patch.object(m, "_migration_files", return_value=[]):
        m.run_migrations(conn)

    first_sql = cur.execute.call_args_list[0][0][0]
    assert "pg_advisory_xact_lock" in first_sql
    assert "8314" in str(cur.execute.call_args_list[0])


def test_run_migrations_creates_tracking_table():
    conn, cur = make_conn()
    cur.fetchall.return_value = []

    with patch.object(m, "_migration_files", return_value=[]):
        m.run_migrations(conn)

    all_sql = " ".join(str(call) for call in cur.execute.call_args_list)
    assert "_migrations_docs" in all_sql


def test_migration_files_returns_sql_files_in_lexical_order(tmp_path):
    """The sort lives in _migration_files, so it must be tested against the real
    filesystem. Files are created out of order and a non-.sql file is included 
    to prove it is filtered."""
    (tmp_path / "0002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "0010_tenth.sql").write_text("SELECT 10;", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "notes.md").write_text("not a migration", encoding="utf-8")

    with patch.object(m, "MIGRATIONS_DIR", tmp_path):
        names = [p.name for p in m._migration_files()]

    assert names == ["0001_first.sql", "0002_second.sql", "0010_tenth.sql"]


def test_migration_files_returns_empty_when_dir_missing(tmp_path):
    with patch.object(m, "MIGRATIONS_DIR", tmp_path / "does_not_exist"):
        assert m._migration_files() == []


def test_run_migrations_applies_pending_files_in_the_order_given(tmp_path):
    conn, cur = make_conn()
    cur.fetchall.return_value = []

    first = tmp_path / "0001_first.sql"
    first.write_text("SELECT 1;", encoding="utf-8")
    second = tmp_path / "0002_second.sql"
    second.write_text("SELECT 2;", encoding="utf-8")

    with patch.object(m, "_migration_files", return_value=[first, second]):
        applied = m.run_migrations(conn)

    assert applied == 2
    executed = [str(call) for call in cur.execute.call_args_list]
    first_idx = next(i for i, e in enumerate(executed) if "SELECT 1;" in e)
    second_idx = next(i for i, e in enumerate(executed) if "SELECT 2;" in e)
    assert first_idx < second_idx


def test_run_migrations_skips_already_applied_files(tmp_path):
    conn, cur = make_conn()
    cur.fetchall.return_value = [("0001_first.sql",)]

    first = tmp_path / "0001_first.sql"
    first.write_text("SELECT 1;", encoding="utf-8")

    with patch.object(m, "_migration_files", return_value=[first]):
        applied = m.run_migrations(conn)

    assert applied == 0
    executed = " ".join(str(call) for call in cur.execute.call_args_list)
    assert "SELECT 1;" not in executed


def test_run_migrations_commits_once_at_the_end(tmp_path):
    conn, cur = make_conn()
    cur.fetchall.return_value = []

    first = tmp_path / "0001_first.sql"
    first.write_text("SELECT 1;", encoding="utf-8")

    with patch.object(m, "_migration_files", return_value=[first]):
        m.run_migrations(conn)

    conn.commit.assert_called_once()


def test_get_db_connection_does_not_run_migrations():
    """Migrations belong to the indexer, not to every reader. CREATE EXTENSION
    needs privileges managed Postgres withholds, so a reader that triggers it
    500s on a deployment that never enabled the Postgres docsite backend."""
    import util

    with patch.object(util, "psycopg2") as mock_psycopg2, \
         patch.object(m, "run_migrations") as mock_run, \
         patch.dict("os.environ", {"POSTGRES_URL": "postgresql://user@host/db"}):
        conn = util.get_db_connection()

    assert conn is mock_psycopg2.connect.return_value
    mock_run.assert_not_called()

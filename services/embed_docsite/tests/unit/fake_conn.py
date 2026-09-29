"""A psycopg2-shaped connection that models transaction state.

MagicMock let two defects through: `conn.autocommit = True` on a mock is an
inert attribute write, but psycopg2 raises `set_session cannot be used inside a
transaction` when a transaction is open — and a bare SELECT is enough to open
one. This models the state machine those defects depend on.
"""

import psycopg2
from psycopg2.extensions import STATUS_IN_TRANSACTION, STATUS_READY


class FakeCursor:
    """Cursor serving rows from its connection's queued results."""

    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, params=None):
        self._conn._record(sql, params)
        self._rows, self.rowcount = self._conn._pop_result()

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeConn:
    """psycopg2-shaped connection modelling the transaction state machine.

    :param results: FIFO consumed one entry per execute(). An entry may be a
        list of rows, an int meaning "no rows, but report this rowcount" (as
        INSERT and DELETE do), or None. An exhausted queue yields no rows.
    :param fail_on: substring; an execute() whose SQL contains it raises and
        leaves the connection aborted, as psycopg2 would.
    """

    def __init__(self, results=None, fail_on=None):
        # _guard off while __init__ populates state, so the autocommit check
        # below does not fire before `status` exists.
        object.__setattr__(self, "_guard", False)
        self._results = list(results or [])
        self._fail_on = fail_on
        self._failed = False
        self.status = STATUS_READY
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.autocommit = False
        object.__setattr__(self, "_guard", True)

    def __setattr__(self, name, value):
        """Only `autocommit` is guarded — it is the assignment psycopg2 rejects."""
        if name == "autocommit" and self.__dict__.get("_guard") and self.status != STATUS_READY:
            raise psycopg2.ProgrammingError("set_session cannot be used inside a transaction")
        object.__setattr__(self, name, value)

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1
        self.status = STATUS_READY
        self._failed = False

    def rollback(self):
        self.rollbacks += 1
        self.status = STATUS_READY
        self._failed = False

    def close(self):
        self.closed = True

    def _record(self, sql, params):
        if self._failed:
            raise psycopg2.errors.InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of transaction block"
            )
        self.executed.append((sql, params))
        if self._fail_on and self._fail_on in sql:
            self._failed = True
            self.status = STATUS_IN_TRANSACTION
            raise psycopg2.ProgrammingError(f"fake failure on: {self._fail_on}")
        if not self.autocommit:
            self.status = STATUS_IN_TRANSACTION

    def _pop_result(self):
        """Returns (rows, rowcount) for the next queued entry."""
        entry = self._results.pop(0) if self._results else None
        if isinstance(entry, int):
            return [], entry
        rows = list(entry or [])
        return rows, len(rows)

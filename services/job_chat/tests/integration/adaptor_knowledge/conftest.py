"""Guard: skip individual cases whose adaptor docs can't be loaded.

Every case depends on job_chat receiving a real adaptor block. When the docs
pipeline can't supply one, the prompt silently degrades to "The user is using
an OpenFn Adaptor to write the job." and the case fails for a reason that has
nothing to do with what it measures. Skipping is the honest outcome — a red
test should mean the model got the API wrong, not that the fixture was empty.

The check is per adaptor version, not per session, because the version-pinned
cases in the `version` group deliberately reference old releases that a given
machine may not have.

Known local cause: jsdoc doesn't run under bun (JSDOC_BUN_ERROR.md), so
adaptor_apis can't generate docs and the auto-load path fails. See the README
for the seeding workaround.
"""

import pytest
from util import AdaptorSpecifier, get_db_connection


def _version_present(conn, spec: str) -> bool:
    adaptor = AdaptorSpecifier(spec)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM adaptor_function_docs "
            "WHERE adaptor_name = %s AND version = %s LIMIT 1",
            (adaptor.name, adaptor.version),
        )
        return cur.fetchone() is not None


@pytest.fixture(scope="session")
def loaded_adaptor_versions():
    """Set of adaptor specifiers that already have docs in the database.

    Empty set (rather than a skip) when the database is unreachable — the
    per-case fixture turns that into a skip with a clearer message.
    """
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"\nadaptor_knowledge: no database connection ({e}); all cases will skip")
        return set()

    present = set()
    try:
        # Import here so a collection-time import cycle can't break the fixture.
        from .cases import ALL_CASES  # noqa: PLC0415

        for spec in sorted({c.adaptor for c in ALL_CASES}):
            try:
                if _version_present(conn, spec):
                    present.add(spec)
            except Exception:
                break
    finally:
        conn.close()

    return present


@pytest.fixture
def require_adaptor_docs(loaded_adaptor_versions):
    """Skip a case unless its exact adaptor version has docs available.

    Returns a callable so the test can pass its own specifier in. Auto-loading
    is left to job_chat itself (`download_adaptor_docs` defaults to true); this
    only catches the case where the docs are absent AND can't be generated.
    """

    def _check(spec: str) -> None:
        if spec in loaded_adaptor_versions:
            return
        pytest.skip(
            f"no adaptor docs for {spec}. job_chat auto-loads on first use where "
            f"adaptor_apis works; if it doesn't on this machine, see the README "
            f"in this directory for the seeding workaround.",
        )

    return _check


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Print the per-group scoreboard. Silent unless these cases ran."""
    from .scoreboard import render  # noqa: PLC0415

    out = render()
    if out:
        print(out)

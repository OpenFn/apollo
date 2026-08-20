"""Prints the scoreboard at the end of the run.

The hook has to live here: pytest does not call session hooks defined in test
modules, and the tally itself is in `scoreboard.py` because the test module
writes to it while this reads it.
"""


def pytest_sessionfinish(session: object, exitstatus: int) -> None:  # noqa: ARG001
    """Print the per-group scoreboard. Silent unless these cases ran."""
    from .scoreboard import render  # noqa: PLC0415

    out = render()
    if out:
        print(out)  # noqa: T201 — the scoreboard is the point of the run

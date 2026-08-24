"""Shared result tally for the adaptor-knowledge run.

Lives in its own module because the test file records into it while the
`pytest_sessionfinish` hook that prints it must live in conftest.py — pytest
does not call session hooks defined in test modules.
"""

RESULTS: list[tuple[str, str, bool]] = []
"""One entry per case run, as (case_id, group, passed)."""


def record(case_id: str, group: str, passed: bool) -> None:
    RESULTS.append((case_id, group, passed))


def render() -> str:
    """Per-group scoreboard. Empty string when nothing ran."""
    if not RESULTS:
        return ""

    by_group: dict[str, list[bool]] = {}
    for _, group, ok in RESULTS:
        by_group.setdefault(group, []).append(ok)

    width = max(len(g) for g in by_group) + 2
    lines = ["", "=== Adaptor knowledge ==="]
    for group, oks in by_group.items():
        lines.append(f"  {group:<{width}}{sum(oks)}/{len(oks)} pass")

    passed = sum(1 for _, _, ok in RESULTS if ok)
    lines.append(f"  {'TOTAL':<{width}}{passed}/{len(RESULTS)} pass")

    failed = [cid for cid, _, ok in RESULTS if not ok]
    if failed:
        lines.append("")
        lines.append("  failing:")
        lines.extend(f"    x {cid}" for cid in failed)

    return "\n".join(lines)

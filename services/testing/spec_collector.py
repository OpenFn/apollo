"""Pytest plugin: collect acceptance test markdown specs and run them.

Detects `*.md` files (excluding `_*.md`) inside any `acceptance/` folder under
the configured testpaths. Each spec becomes one or more pytest items
(`spec.runs` defaults to 1; multi-run specs yield `<id>[run=N]` items).

Each item:
  1. Builds the service payload from `# settings`, `# history`, and `# turn`.
  2. Dispatches to the named service via ApolloClient.
  3. Calls `judge.evaluate()` with the spec's quality_criteria.
  4. Fails with the judge's reasoning summary if `verdict.passed` is False.
"""

import pytest

from testing import judge
from testing.apollo_client import ApolloClient
from testing.spec_parser import Spec, parse_spec


# Verdicts collected across the session for the end-of-run rollup.
# Each entry is (spec_id, Verdict).
_session_verdicts: list[tuple[str, judge.Verdict]] = []


def pytest_collect_file(parent, file_path):
    if (
        file_path.suffix == ".md"
        and not file_path.name.startswith("_")
        and file_path.parent.name == "acceptance"
    ):
        return SpecFile.from_parent(parent, path=file_path)


class SpecFile(pytest.File):
    def collect(self):
        spec = parse_spec(self.path)
        for run_index in range(spec.runs):
            suffix = f"[run={run_index}]" if spec.runs > 1 else ""
            yield SpecItem.from_parent(
                self,
                name=f"{spec.id}{suffix}",
                spec=spec,
                run_index=run_index,
            )


class SpecItem(pytest.Item):
    def __init__(self, *, name, parent, spec: Spec, run_index: int):
        super().__init__(name, parent)
        self.spec = spec
        self.run_index = run_index

    def runtest(self):
        spec = self.spec
        print(f"\n→ {spec.id}")
        print(f"  service: {spec.service}")
        print(f"  judges:  {', '.join(spec.judges)}")

        payload = _build_payload(spec)
        client = ApolloClient()

        print(f"  calling {spec.service}...", flush=True)
        response = client.call(spec.service, payload)
        print("  ✓ service responded")

        # One service call, N judges evaluate the same response.
        # Consensus: the test passes only if every judge passes.
        verdicts = []
        for judge_name in spec.judges:
            print(f"  judging with {judge_name}...", flush=True)
            v = judge.evaluate(
                criteria=spec.quality_criteria,
                candidate=response,
                test_notes=spec.notes or None,
                judge=judge_name,
            )
            mark = "✓" if v.passed else "✗"
            print(f"  {mark} {judge_name}: {'PASS' if v.passed else 'FAIL'} "
                  f"(score={v.score:.2f}, flags={len(v.general_flags)})")
            verdicts.append(v)
            _session_verdicts.append((spec.id, v))

        failing = [v for v in verdicts if not v.passed]
        if failing:
            summary = "\n\n".join(v.summary for v in failing)
            raise AssertionError(summary)

    def repr_failure(self, excinfo, style=None):
        return str(excinfo.value)

    def reportinfo(self):
        return self.path, 0, f"acceptance: {self.spec.id}"


def _build_payload(spec: Spec) -> dict:
    """Assemble the JSON payload from a parsed spec.

    Settings is the base. History (if present) goes into the `history` key.
    The current turn's content (if present and role=user) goes into `content`.
    """
    payload = dict(spec.settings)

    if spec.history:
        payload["history"] = spec.history

    if spec.current_turn and spec.current_turn.get("role") == "user":
        payload["content"] = spec.current_turn["content"]

    return payload


def pytest_sessionfinish(session, exitstatus):
    """Print an acceptance-tier rollup after the session ends.

    Only fires when at least one acceptance spec ran. Stays silent on unit /
    integration runs.
    """
    if not _session_verdicts:
        return

    by_test: dict[str, list[judge.Verdict]] = {}
    for spec_id, v in _session_verdicts:
        by_test.setdefault(spec_id, []).append(v)

    by_judge: dict[str, list[judge.Verdict]] = {}
    for _, v in _session_verdicts:
        by_judge.setdefault(v.judge_name, []).append(v)

    test_pass_count = sum(1 for vs in by_test.values() if all(v.passed for v in vs))
    test_total = len(by_test)
    pct = (test_pass_count / test_total * 100) if test_total else 0

    avg_score = sum(v.score for _, v in _session_verdicts) / len(_session_verdicts)

    flag_counts = {"note": 0, "regression": 0}
    for _, v in _session_verdicts:
        for f in v.general_flags:
            flag_counts[f.severity] = flag_counts.get(f.severity, 0) + 1

    failing = [(tid, vs) for tid, vs in by_test.items() if not all(v.passed for v in vs)]

    judge_col = max(len(name) for name in by_judge) + 2

    print()
    print("=== Acceptance summary ===")
    print(f"Tests:  {test_pass_count}/{test_total} passed ({pct:.0f}%)")
    print(f"Average score across all verdicts: {avg_score:.2f}")
    print()
    print("Per judge:")
    for judge_name in sorted(by_judge):
        verdicts = by_judge[judge_name]
        passed = sum(1 for v in verdicts if v.passed)
        print(f"  {judge_name:<{judge_col}}{passed}/{len(verdicts)} pass")
    print()
    print("Flags:")
    for severity in ("regression", "note"):
        print(f"  {severity:12} {flag_counts.get(severity, 0)}")

    if failing:
        print()
        print("Failing tests:")
        for spec_id, verdicts in failing:
            print(f"  {spec_id}")
            for v in verdicts:
                if v.passed:
                    continue
                n_reg = sum(1 for f in v.general_flags if f.severity == "regression")
                n_note = sum(1 for f in v.general_flags if f.severity == "note")
                detail = []
                if n_reg:
                    detail.append(f"{n_reg} regression")
                if n_note:
                    detail.append(f"{n_note} note")
                if v.score < 1.0:
                    n_failed_criteria = sum(1 for c in v.criteria if not c.passed)
                    detail.append(f"{n_failed_criteria} criterion fail")
                detail_str = ", ".join(detail) if detail else "—"
                print(f"    ✗ {v.judge_name}  ({detail_str})")

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
        payload = _build_payload(self.spec)
        client = ApolloClient()
        response = client.call(self.spec.service, payload)

        # One service call, N judges evaluate the same response.
        # Consensus: the test passes only if every judge passes.
        verdicts = [
            judge.evaluate(
                criteria=self.spec.quality_criteria,
                candidate=response,
                test_notes=self.spec.notes or None,
                judge=judge_name,
            )
            for judge_name in self.spec.judges
        ]

        if not all(v.passed for v in verdicts):
            summary = "\n\n".join(v.summary for v in verdicts)
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

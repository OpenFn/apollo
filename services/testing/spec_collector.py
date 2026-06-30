"""Pytest plugin: collect acceptance test markdown specs and run them.

Detects `*.md` files (excluding `_*.md`) inside any `acceptance/` folder under
the configured testpaths. Each spec becomes one or more pytest items
(`spec.runs` defaults to 1; multi-run specs yield `<id>[run=N]` items).

Each item:
  1. Builds the service payload from `# settings`, `# history`, and `# turn`.
  2. Dispatches to the named service via ApolloClient.
  3. Captures any YAML in the response to a `tmp/` folder next to the spec
     file (e.g. `services/workflow_chat/tests/acceptance/tmp/<spec_id>.yaml`).
  4. Calls `judge.evaluate()` with the spec's quality_criteria.
  5. Fails with the judge's reasoning summary if `verdict.passed` is False.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from testing import judge
from testing.apollo_client import ApolloClient
from testing.spec_parser import Spec, parse_spec


# Verdicts collected across the session for the end-of-run rollup.
# Each entry is (spec_id, Verdict).
_session_verdicts: list[tuple[str, judge.Verdict]] = []


def pytest_addoption(parser):
    parser.addoption(
        "-E",
        "--experiment",
        action="store",
        default="",
        help="Optional experiment label appended to captured output filenames "
        "in tmp/ (e.g. --experiment=sonnet-2026-06-29) so runs with different "
        "settings/dates don't overwrite each other.",
    )


def _experiment_suffix(config) -> str:
    """Filesystem-safe `__<experiment>` suffix, or '' if no experiment given.

    `__` is the reserved metadata-boundary separator (the spec id and extension
    use `.`/`-` but never `__`), so a downstream `name.split("__")` can recover
    the fields. We collapse any `_` runs in the label to a single `_` so a user
    label can't inject a false field boundary.
    """
    raw = (config.getoption("experiment") or "").strip()
    if not raw:
        return ""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", raw)
    safe = re.sub(r"_+", "_", safe).strip("-_")
    return f"__{safe}" if safe else ""


def pytest_collect_file(parent, file_path):
    if (
        file_path.suffix == ".md"
        and not file_path.name.startswith("_")
        and "acceptance" in file_path.parts
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

        tmp_dir = self.path.parent / "tmp"
        experiment = _experiment_suffix(self.config)

        yaml_path = _capture_response_yaml(
            response, spec.id, self.run_index, spec.runs, tmp_dir, experiment
        )
        if yaml_path is not None:
            print(f"  ✓ project YAML saved to {yaml_path}")

        text_path = _capture_response_text(
            response, spec.id, self.run_index, spec.runs, tmp_dir, experiment
        )
        if text_path is not None:
            print(f"  ✓ response text saved to {text_path}")

        # One service call, N judges evaluate the same response in parallel.
        # Consensus: the test passes only if every judge passes.
        def _run_judge(judge_name: str) -> judge.Verdict:
            return judge.evaluate(
                criteria=spec.quality_criteria,
                candidate=response,
                test_notes=spec.notes or None,
                request=payload,
                judge=judge_name,
            )

        print(f"  running {len(spec.judges)} judge(s) in parallel...", flush=True)
        with ThreadPoolExecutor(max_workers=len(spec.judges)) as executor:
            verdicts = list(executor.map(_run_judge, spec.judges))

        for judge_name, v in zip(spec.judges, verdicts):
            mark = "✓" if v.passed else "✗"
            print(f"  {mark} {judge_name}: {'PASS' if v.passed else 'FAIL'} "
                  f"(score={v.score:.2f}, flags={len(v.general_flags)})")
            _session_verdicts.append((spec.id, v))

        judges_path = _capture_judge_verdicts(
            verdicts, spec.id, self.run_index, spec.runs, tmp_dir, experiment
        )
        if judges_path is not None:
            print(f"  ✓ judge verdicts saved to {judges_path}")

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


def _extract_yaml_from_response(response: dict) -> str | None:
    """Pull the full project YAML out of a service response, if any.

    Different services use different keys:
      - workflow_chat: `response_yaml`
      - global_chat: `attachments` list with `type=workflow_yaml`
    Falls back to `workflow_yaml` / `content_yaml` for any other service that
    might use them.
    """
    if not isinstance(response, dict):
        return None

    for key in ("response_yaml", "workflow_yaml", "content_yaml"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value

    for attachment in response.get("attachments") or []:
        if (
            isinstance(attachment, dict)
            and attachment.get("type") == "workflow_yaml"
            and isinstance(attachment.get("content"), str)
            and attachment["content"].strip()
        ):
            return attachment["content"]

    return None


def _capture_response_yaml(
    response: dict,
    spec_id: str,
    run_index: int,
    runs: int,
    output_dir: Path,
    experiment: str = "",
) -> Path | None:
    """Write the response's project YAML to `output_dir/<spec_id>.yaml`.

    For multi-run specs, appends `__run-N` to the filename so each run is
    preserved. `experiment` (already a `__<label>` suffix or '') is appended
    last so runs with different settings don't overwrite each other. Returns
    the written path, or None if no YAML was present.
    """
    yaml_str = _extract_yaml_from_response(response)
    if yaml_str is None:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"__run-{run_index}" if runs > 1 else ""
    safe_id = spec_id.replace("/", "_")
    path = output_dir / f"{safe_id}{suffix}{experiment}.yaml"
    path.write_text(yaml_str)
    return path


def _format_agent_path(meta: dict) -> str | None:
    """Build an arrow-separated path showing which agents handled the request.

    Uses `subagent_calls` (in-order, with repetitions) when present so a
    planner that called the job_code agent twice shows as
    `router -> planner -> job_code_agent -> job_code_agent`. Falls back to
    the deduped `agents` list for direct routes.
    """
    if not isinstance(meta, dict):
        return None

    subagent_calls = meta.get("subagent_calls")
    if isinstance(subagent_calls, list) and subagent_calls:
        ordered = ["router", "planner"]
        for call in subagent_calls:
            if not isinstance(call, dict):
                continue
            name = call.get("_call_metadata", {}).get("subagent")
            if name:
                ordered.append(name)
        return " -> ".join(ordered)

    agents = meta.get("agents")
    if isinstance(agents, list) and agents:
        return " -> ".join(str(a) for a in agents)

    return None


def _capture_response_text(
    response: dict,
    spec_id: str,
    run_index: int,
    runs: int,
    output_dir: Path,
    experiment: str = "",
) -> Path | None:
    """Write the agent path and response text to `output_dir/<spec_id>.txt`."""
    if not isinstance(response, dict):
        return None
    text = response.get("response")
    if not isinstance(text, str) or not text.strip():
        return None

    agent_path = _format_agent_path(response.get("meta", {}))
    body = f"agents: {agent_path}\n\n{text}" if agent_path else text

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"__run-{run_index}" if runs > 1 else ""
    safe_id = spec_id.replace("/", "_")
    path = output_dir / f"{safe_id}{suffix}{experiment}.txt"
    path.write_text(body)
    return path


def _capture_judge_verdicts(
    verdicts: list[judge.Verdict],
    spec_id: str,
    run_index: int,
    runs: int,
    output_dir: Path,
    experiment: str = "",
) -> Path | None:
    """Write the judge verdicts to `output_dir/<spec_id>.judges.txt`.

    Reuses the same formatting printed during the run: a one-line header per
    judge (`✓ general: PASS (score=..., flags=...)`) followed by that judge's
    `verdict.summary` block (criteria + reasoning + flags).
    """
    if not verdicts:
        return None

    blocks = []
    for v in verdicts:
        mark = "✓" if v.passed else "✗"
        header = (f"{mark} {v.judge_name}: {'PASS' if v.passed else 'FAIL'} "
                  f"(score={v.score:.2f}, flags={len(v.general_flags)})")
        blocks.append(f"{header}\n\n{v.summary}")
    body = "\n\n===\n\n".join(blocks) + "\n"

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"__run-{run_index}" if runs > 1 else ""
    safe_id = spec_id.replace("/", "_")
    path = output_dir / f"{safe_id}.judges{suffix}{experiment}.txt"
    path.write_text(body)
    return path


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

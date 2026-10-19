"""Run the staged web-tools experiment and print one comparison table per stage.

Runs are cached in tmp/ keyed by variant, config fingerprint, scenario and run
index. Delete a file to re-run that cell.

From the repo root:
    PYTHONUTF8=1 PYTHONPATH=services python -m poetry run python -m global_chat.tests.web_tools.run_web_experiments --stage 0
    ... --stage 1 --carry base
    ... --stage 2 --carry base+1c --variants 20k,30k
    ... --scenario fhir_deep --carry base --runs 1
"""

# ruff: noqa: T201 - a command-line report, where printing is its output

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
load_dotenv()

from .metrics import RunRecord, format_table, pick_winner, summarise  # noqa: E402
from .recording import fingerprint, run_scenario, scenario_key  # noqa: E402
from .scenarios import SCENARIOS, Scenario  # noqa: E402
from .trace import format_trace  # noqa: E402
from .variants import STAGES, resolve_variant  # noqa: E402

TMP = Path(__file__).parent / "tmp"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", type=int, choices=sorted(STAGES), default=0)
    parser.add_argument("--carry", default="base", help="variant carried forward from the previous stage")
    parser.add_argument("--variants", default="", help="comma-separated parts overriding the stage's variants")
    parser.add_argument("--scenario", default="", help="run one scenario for the carried variant and print it in full")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    if os.getenv("ANTHROPIC_BASE_URL"):
        sys.exit("ANTHROPIC_BASE_URL is set, the web tools need a direct api.anthropic.com key")

    if args.scenario:
        contestants, scenario_ids = [args.carry], [args.scenario]
    else:
        stage = STAGES[args.stage]
        parts = [p for p in args.variants.split(",") if p] or stage["variants"]
        contestants = [args.carry] + [f"{args.carry}+{p}" for p in parts]
        scenario_ids = stage["scenarios"]

    table: dict[str, dict[str, dict]] = {}
    for variant_name in contestants:
        table[variant_name] = {}
        for scenario_id in scenario_ids:
            scenario = SCENARIOS[scenario_id]
            runs = [load_or_run(variant_name, scenario, i) for i in range(args.runs)]
            table[variant_name][scenario_id] = summarise(runs, scenario.facts, scenario.source_page)
            if args.scenario:
                for run in runs:
                    print_run(run)

    report = format_table(table)
    if not args.scenario and args.stage > 0:
        controls = [s for s in scenario_ids if SCENARIOS[s].control]
        complexity = {v: resolve_variant(v).complexity for v in table}
        winner, reasons = pick_winner(args.stage, table, controls, complexity)
        report += "\n\n" + "\n".join(reasons) + f"\n\nwinner: {winner}"

    print("\n" + report)
    if not args.scenario:
        TMP.mkdir(exist_ok=True)
        (TMP / f"stage-{args.stage}__{args.carry}.md").write_text(report + "\n", encoding="utf-8")


def load_or_run(variant_name: str, scenario: Scenario, run_index: int) -> RunRecord:
    path = cache_path(TMP, variant_name, scenario, run_index)
    cached = cached_run(path)
    if cached is not None:
        return RunRecord(cached.scenario_id, variant_name, run_index, cached.turns)

    print(f"running {variant_name} / {scenario.id} / run {run_index}", flush=True)
    record = RunRecord(scenario.id, variant_name, run_index, run_scenario(scenario, resolve_variant(variant_name)))
    TMP.mkdir(exist_ok=True)
    path.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
    return record


def cache_path(directory: Path, variant_name: str, scenario: Scenario, run_index: int) -> Path:
    key = fingerprint(resolve_variant(variant_name))
    return directory / f"{key}__{scenario.id}-{scenario_key(scenario)}__run-{run_index}.json"


def cached_run(path: Path) -> RunRecord | None:
    """A cached run, or None to re-run it. A failed run is retried."""
    if not path.exists():
        return None
    record = RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if any(turn.error for turn in record.turns):
        print(f"retrying {path.name}, it failed last time", flush=True)
        return None
    return record


def print_run(run: RunRecord) -> None:
    for number, turn in enumerate(run.turns, start=1):
        print(f"\n--- {run.variant} / {run.scenario_id} / run {run.run_index} / turn {number}")
        if turn.error:
            print(f"ERROR: {turn.error}")
        print(format_trace(turn.trace))
        print(f"\n{turn.answer}")


if __name__ == "__main__":
    main()

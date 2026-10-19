"""Unit tests for the experiment runner's run cache."""

import json
from dataclasses import asdict
from pathlib import Path

from global_chat.tests.web_tools import run_web_experiments as runner
from global_chat.tests.web_tools.metrics import RunRecord, TurnRecord
from global_chat.tests.web_tools.scenarios import SCENARIOS

USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
SCENARIO = SCENARIOS["fhir_shallow"]


def turn(error: str | None = None) -> TurnRecord:
    return TurnRecord(answer="a", trace=[], usage=USAGE, seconds=1.0, rounds=1, error=error)


def write(path: Path, *turns: TurnRecord) -> None:
    record = RunRecord(SCENARIO.id, "base+1a", 0, list(turns))
    path.write_text(json.dumps(asdict(record)), encoding="utf-8")


def test_variants_with_the_same_prompt_share_one_cache_file(tmp_path: Path) -> None:
    """base and base+1a render the same prompt since 1a shipped."""
    assert runner.cache_path(tmp_path, "base", SCENARIO, 0) == runner.cache_path(tmp_path, "base+1a", SCENARIO, 0)
    assert runner.cache_path(tmp_path, "base", SCENARIO, 0) != runner.cache_path(tmp_path, "base+1b", SCENARIO, 0)


def test_a_cached_successful_run_is_reused(tmp_path: Path) -> None:
    path = runner.cache_path(tmp_path, "base", SCENARIO, 0)
    write(path, turn())

    assert runner.cached_run(path) is not None


def test_a_cached_failed_run_is_not_reused(tmp_path: Path) -> None:
    path = runner.cache_path(tmp_path, "base", SCENARIO, 0)
    write(path, turn(), turn(error="ApolloError: overloaded"))

    assert runner.cached_run(path) is None


def test_a_missing_cache_file_is_not_a_hit(tmp_path: Path) -> None:
    assert runner.cached_run(tmp_path / "absent.json") is None

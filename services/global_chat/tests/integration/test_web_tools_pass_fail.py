"""Live checks on how the planner uses web_search and web_fetch.

These hit the live Anthropic API. Each test plays its scenario 
once with the shipped prompt and config and asserts on the recorded 
tool-call trace. A failure prints the full trace, no retries.
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from global_chat.tests.web_tools.metrics import TurnRecord, is_grounded  # noqa: E402
from global_chat.tests.web_tools.recording import run_scenario  # noqa: E402
from global_chat.tests.web_tools.scenarios import SCENARIOS  # noqa: E402
from global_chat.tests.web_tools.trace import count, format_trace  # noqa: E402
from global_chat.tests.web_tools.variants import resolve_variant  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(bool(os.getenv("ANTHROPIC_BASE_URL")), reason="web tools need a direct api.anthropic.com key"),
]


@pytest.mark.parametrize("scenario_id", ["control_openfn_concept", "control_code_edit"])
def test_controls_make_no_web_calls(scenario_id: str) -> None:
    turns = play(scenario_id)
    calls = all_calls(turns)

    assert count(calls, tool="search") + count(calls, tool="fetch") == 0, explain(turns)


@pytest.mark.parametrize("scenario_id", ["fhir_shallow", "fhir_deep"])
def test_fhir_answers_come_from_a_fetched_page(scenario_id: str) -> None:
    turns = play(scenario_id)
    calls = all_calls(turns)

    assert count(calls, result="url_not_in_prior_context") == 0, explain(turns)
    assert count(calls, tool="fetch", result="ok") >= 1, explain(turns)
    assert is_grounded(turns[-1].answer, calls, SCENARIOS[scenario_id].facts), explain(turns)


def test_an_off_allowlist_question_does_not_try_banned_urls() -> None:
    turns = play("off_allowlist")
    calls = all_calls(turns)

    assert count(calls, result="url_not_allowed") == 0, explain(turns)
    assert count(calls, result="url_not_in_prior_context") == 0, explain(turns)


def test_follow_up_turns_do_not_fetch_the_same_content_again() -> None:
    turns = play("multi_turn")

    assert sum(count(turn.trace, tool="fetch") for turn in turns[1:]) <= 1, explain(turns)
    assert count(all_calls(turns), result="url_not_in_prior_context") == 0, explain(turns)


def play(scenario_id: str) -> list[TurnRecord]:
    turns = run_scenario(SCENARIOS[scenario_id], resolve_variant("base"))
    for turn in turns:
        assert turn.error is None, f"turn failed: {turn.error}"
        assert not turn.downgraded, "web tools were downgraded, so this key cannot use web search"
    return turns


def all_calls(turns: list[TurnRecord]) -> list[dict]:
    return [call for turn in turns for call in turn.trace]


def explain(turns: list[TurnRecord]) -> str:
    return "\n\n".join(
        f"turn {number}:\n{format_trace(turn.trace)}\n\nanswer:\n{turn.answer[:1500]}"
        for number, turn in enumerate(turns, start=1)
    )
